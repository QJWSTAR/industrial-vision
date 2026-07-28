function [pointlist_out, feed_rates_out, layer_indices_out, meta_out] = ...
    run_path_planning(stl_path, params)
% RUN_PATH_PLANNING  CSAM 路径规划统一入口（供 matlab.engine 调用）
%
% 串联管线：read_stl_file -> model_process -> layer_slice -> generate_path
% 全部内存返回，不写 .mat 文件，不运行离线 main.m。
%
% 输入：
%   stl_path : char    STL 文件绝对路径
%   params   : struct  工艺参数，字段如下：
%       .base_plane            (double, 默认 5.0)
%       .layer_height          (double, 默认 2.0)
%       .buffer_additive       (double, 默认 2.0)
%       .buffer_repairing      (double, 默认 0.0)
%       .scanning_angle        (double, 默认 -45.0)
%       .scanning_step         (double, 默认 2.0)
%       .edge_step_size        (double, 默认 2.0)
%       .tilt_angle            (double, 默认 60.0)
%       .link_path_free_dist   (double, 默认 20.0)
%       .resolution            (double, 默认 2.0)
%       .traversing_speed_mms  (double, 默认 500.0)
%
% 输出（全部内存数组，可直接被 matlab.engine 转 numpy）：
%   pointlist_out     : M×6 double  [x, y, z, nx, ny, nz]
%   feed_rates_out    : M×1 double  进给速度 (mm/s)
%   layer_indices_out : M×1 double  层号（从 1 起）
%   meta_out          : struct      附加信息
%       .waypoint_count
%       .compute_time_s
%       .layer_count
%       .x_min / .x_max / .y_min / .y_max
%       .warning_msg

    t0 = tic;
    meta_out = struct('waypoint_count', 0, 'compute_time_s', 0, ...
                      'layer_count', 0, 'warning_msg', '');

    % ---- 参数默认值 ----
    if nargin < 2 || isempty(params)
        params = struct();
    end
    defaults = struct( ...
        'base_plane', 5.0, ...
        'layer_height', 2.0, ...
        'buffer_additive', 2.0, ...
        'buffer_repairing', 0.0, ...
        'scanning_angle', -45.0, ...
        'scanning_step', 2.0, ...
        'edge_step_size', 2.0, ...
        'tilt_angle', 60.0, ...
        'link_path_free_dist', 20.0, ...
        'resolution', 2.0, ...
        'traversing_speed_mms', 500.0, ...
        'request_id', '');
    params = complete_struct(params, defaults);

    % ---- 1. 读取 STL ----
    assert_not_cancelled(params.request_id, 'before STL loading');
    if ~exist(stl_path, 'file')
        error('STL file not found: %s', stl_path);
    end
    triangles = read_stl_file(stl_path);   % N×12

    % ---- 2. 模型预处理 ----
    assert_not_cancelled(params.request_id, 'before model preprocessing');
    [all_triangles, additive_cluster, repairing_clusters, ...
     x_min, x_max, y_min, y_max] = ...
        model_process(triangles, 1.0, 1e-8, params.base_plane);

    % ---- 3. 切片 ----
    assert_not_cancelled(params.request_id, 'before slicing');
    [additive_layerlist, repairing_layerlist] = ...
        layer_slice(additive_cluster, repairing_clusters, ...
                    params.layer_height, params.base_plane);

    % ---- 4. 路径生成 ----
    progress_callback = @(layer_idx, total_layers, layer_points, layer_velocity) ...
        publish_path_layer(params.request_id, layer_idx, total_layers, ...
                           layer_points, layer_velocity, ...
                           params.traversing_speed_mms, t0);
    cancel_callback = @() is_cancel_requested(params.request_id);
    [pointlist, velocitylist, zonelist] = ...
        generate_path(additive_layerlist, repairing_layerlist, ...
            params.buffer_additive, params.buffer_repairing, ...
            params.scanning_angle, params.scanning_step, ...
            params.edge_step_size, params.tilt_angle, ...
            x_min, x_max, y_min, y_max, ...
            params.link_path_free_dist, params.resolution, ...
            progress_callback, cancel_callback);

    % ---- 5. 速度字符串转数值 ----
    feed_rates_out = velocity_to_numeric(velocitylist, params.traversing_speed_mms);

    % ---- 6. 层号推导 ----
    layer_indices_out = derive_layer_indices(pointlist, ...
        repairing_layerlist, additive_layerlist, params.base_plane);

    % ---- 7. 输出 ----
    pointlist_out = pointlist;   % M×6
    meta_out.waypoint_count = size(pointlist_out, 1);
    meta_out.compute_time_s = toc(t0);
    if isempty(layer_indices_out)
        meta_out.layer_count = 0;
    else
        meta_out.layer_count = max(layer_indices_out);
    end
    meta_out.x_min = x_min;  meta_out.x_max = x_max;
    meta_out.y_min = y_min;  meta_out.y_max = y_max;

    publish_path_completed(params.request_id, meta_out, t0);
end

%% ====== 辅助函数 ======

function s = complete_struct(s, defaults)
% 用 defaults 的字段填充 s 中缺失的字段
    fns = fieldnames(defaults);
    for i = 1:length(fns)
        if ~isfield(s, fns{i}) || isempty(s.(fns{i}))
            s.(fns{i}) = defaults.(fns{i});
        end
    end
end

function feed_rates = velocity_to_numeric(velocitylist, default_speed)
% 将 ABB 速度字符串转为数值 (mm/s)
%   "velocity_infill" -> default_speed
%   "velocity_edge"   -> default_speed * 0.6
%   "velocity_link"   -> default_speed * 1.2
%   其他              -> default_speed
    n = length(velocitylist);
    feed_rates = zeros(n, 1);
    for i = 1:n
        v = velocitylist(i);
        if isStringScalar(v) || ischar(v)
            vs = char(v);
            if contains(vs, 'infill')
                feed_rates(i) = default_speed;
            elseif contains(vs, 'edge')
                feed_rates(i) = default_speed * 0.6;
            elseif contains(vs, 'link')
                feed_rates(i) = default_speed * 1.2;
            else
                feed_rates(i) = default_speed;
            end
        else
            feed_rates(i) = default_speed;
        end
    end
end

function layer_indices = derive_layer_indices(pointlist, rep_layerlist, add_layerlist, base_plane)
% 由 pointlist 的 Z 值反推层号
% repairing 层在 base_plane 以下，additive 层在 base_plane 以上
    z_vals = pointlist(:, 3);
    n = size(pointlist, 1);
    layer_indices = zeros(n, 1);

    % 收集所有切片 Z 高度
    z_slices = [];
    layer_type = {};  % 'rep' 或 'add'
    if ~isempty(rep_layerlist)
        for i = 1:length(rep_layerlist)
            if ~isempty(rep_layerlist{i})
                for j = 1:size(rep_layerlist{i}, 1)
                    if ~isempty(rep_layerlist{i}{j, 4}) && ~isempty(rep_layerlist{i}{j, 3})
                        z_slices = [z_slices; rep_layerlist{i}{j, 3}];
                        layer_type = [layer_type; {'rep'}];
                    end
                end
            end
        end
    end
    if ~isempty(add_layerlist)
        for i = 1:length(add_layerlist)
            if ~isempty(add_layerlist{i})
                for j = 1:size(add_layerlist{i}, 1)
                    if ~isempty(add_layerlist{i}{j, 4}) && ~isempty(add_layerlist{i}{j, 3})
                        z_slices = [z_slices; add_layerlist{i}{j, 3}];
                        layer_type = [layer_type; {'add'}];
                    end
                end
            end
        end
    end

    if isempty(z_slices)
        layer_indices = ones(n, 1);
        return;
    end

    % 对每个航点找最近的切片高度
    for i = 1:n
        [~, idx] = min(abs(z_slices - z_vals(i)));
        layer_indices(i) = idx;
    end
end

function cancelled = is_cancel_requested(request_id)
% 通过 MATLAB pyenv 内的线程安全注册表检查协作式取消。
    cancelled = false;
    if isempty(request_id)
        return;
    end
    try
        cancelled = logical(py.repair_app.bridge.operation_control.is_cancel_requested( ...
            char(request_id)));
    catch me
        warning('CSAM:CancelCheckUnavailable', ...
            'Cancellation check unavailable: %s', me.message);
    end
end

function assert_not_cancelled(request_id, checkpoint)
    if is_cancel_requested(request_id)
        error('CSAM:Cancelled', 'Path planning cancelled %s', checkpoint);
    end
end

function publish_path_layer(request_id, layer_idx, total_layers, ...
                            layer_points, layer_velocity, default_speed, t0)
% 每层只发布该层新增路径；Python 按 layer_index 累积，不使用 latest-frame-wins。
    if isempty(request_id)
        return;
    end
    try
        feed_rates = velocity_to_numeric(layer_velocity, default_speed);
        path_payload = [layer_points, feed_rates];
        py.repair_app.bridge.progress_publisher.publish_progress(pyargs( ...
            'request_id', char(request_id), ...
            'stage', int32(1), ...
            'event_type', int32(3), ...
            'layer_index', int32(layer_idx), ...
            'total_layers', int32(total_layers), ...
            'progress', double(0.35 * layer_idx / max(total_layers, 1)), ...
            'message', sprintf('Path layer %d/%d ready', layer_idx, total_layers), ...
            'waypoints', path_payload, ...
            'elapsed_s', double(toc(t0)), ...
            'reliable', true));
    catch me
        warning('CSAM:ProgressPublishFailed', ...
            'Failed to publish path layer %d: %s', layer_idx, me.message);
    end
end

function publish_path_completed(request_id, meta_out, t0)
    if isempty(request_id)
        return;
    end
    try
        py.repair_app.bridge.progress_publisher.publish_progress(pyargs( ...
            'request_id', char(request_id), ...
            'stage', int32(1), ...
            'event_type', int32(9), ...
            'layer_index', int32(meta_out.layer_count), ...
            'total_layers', int32(meta_out.layer_count), ...
            'progress', double(0.35), ...
            'message', sprintf('Path planning completed: %d waypoints', ...
                               meta_out.waypoint_count), ...
            'elapsed_s', double(toc(t0)), ...
            'reliable', true));
    catch me
        warning('CSAM:ProgressPublishFailed', ...
            'Failed to publish path completion: %s', me.message);
    end
end
