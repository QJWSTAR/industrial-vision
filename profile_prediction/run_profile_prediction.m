function result = run_profile_prediction(stl_path, excel_path, params, pointlist_in, velocitylist_in)
% RUN_PROFILE_PREDICTION  CSAM 形貌预测统一入口（供 matlab.engine 调用）
%
% 串联管线：
%   read_STLfile -> recursiveSubdivide -> improveShortEdges
%   -> particleFitting (CFD 粒子分布)
%   -> run_path_planning (内部调用，获取喷涂航点；若 pointlist_in 已提供则跳过)
%   -> spotInterp (喷斑插值)
%   -> [rayMove -> buildOctree -> batchOctreeFilter
%       -> ray_triangle_intersection -> classifyRemovedTriangles
%       -> profilePredict] 逐点循环
%   -> 输出结构体
%
% 全部内存返回，不写 .mat，不运行离线 main.m，不生成 figure/PNG/视频。
%
% 输入：
%   stl_path        : char    基体 STL 文件绝对路径
%   excel_path      : char    CFD 结果 Excel 文件路径；为空时自动在路径规划目录查找
%   params          : struct  工艺参数，字段如下（缺失自动填充默认值）：
%   pointlist_in    : M×6 double 或 []  预计算的喷涂航点；为空时内部调用 run_path_planning
%   velocitylist_in : M×1 string 或 []  预计算的速度列表；为空时内部推导
%       .standoff_distance_mm   (double, 默认 30.0)   喷涂距离 SoD
%       .spot_step_size_mm      (double, 默认 2.0)    喷斑采样步长
%       .subdivide_max_edge     (double, 默认 5.0)    三角形细分最大边长
%       .improve_short_edge     (double, 默认 1.5)    短边优化阈值
%       .octree_max_depth       (double, 默认 6.0)    八叉树最大深度
%       .octree_max_tris        (double, 默认 8.0)    八叉树叶节点最大三角形数
%       .nozzle_diameter_mm     (double, 默认 6.0)    喷嘴直径
%       .traversing_speed_mms   (double, 默认 500.0)  喷枪移动速度
%       .material_density_gcm3  (double, 默认 7.99)   材料密度
%       .particle_velocity_ms   (double, 默认 500.0)  粒子名义速度
%       .critical_velocity_ms   (double, 默认 400.0)  临界速度
%       .particle_size_um       (double, 默认 25.0)   粉末粒径
%       .layer_height_mm        (double, 默认 2.0)    分层厚度
%       .scanning_angle_deg     (double, 默认 -45.0)  扫描角度
%       .scanning_step_mm       (double, 默认 2.0)    扫描间距
%       .edge_step_size_mm      (double, 默认 2.0)    边缘步长
%       .tilt_angle_deg         (double, 默认 60.0)   倾斜角
%       .buffer_additive_mm     (double, 默认 2.0)    增材缓冲
%       .buffer_repairing_mm    (double, 默认 0.0)    修复缓冲
%       .link_path_free_dist_mm (double, 默认 20.0)   过渡路径
%       .obstacle_resolution_mm (double, 默认 2.0)    障碍分辨率
%       .base_plane             (double, 默认 5.0)    基准平面
%       .max_layers             (double, 默认 5.0)    最大层数
%       .num_layers             (double, 默认 3.0)    形貌预测层数
%
% 输出：
%   result : struct
%       .mesh                 : N×9 double  最终沉积表面三角形
%                               [x1,y1,z1,x2,y2,z2,x3,y3,z3]
%       .substrate_triangles  : N×9 double  原始基体三角形（供对比）
%       .layer_profiles       : L×4 double  逐层轮廓
%                               [layer_idx, max_height_mm, avg_height_mm, dep_eff]
%       .particle_distribution: struct      颗粒分布
%           .px, .py          : M×1 double  位置
%           .vx, .vy, .vz     : M×1 double  速度分量
%           .vcr              : M×1 double  临界速度判定 (1=沉积, 0=弹开)
%           .dep_efficiency   : 1×1 double  总体沉积效率
%           .diameter         : M×1 double  粒径 (um)
%           .temperature      : M×1 double  温度 (K)
%       .uniformity           : 1×1 double  均匀性评分 [0, 1]
%       .estimated_mass_g     : 1×1 double  估算材料用量
%       .estimated_time_s     : 1×1 double  预估修复耗时
%       .predicted_volume_mm3 : 1×1 double  预测填充体积
%       .warnings             : 1×N cell    警告信息
%       .compute_time_s       : 1×1 double  计算耗时
%       .waypoint_count       : 1×1 double  航点数

    t0 = tic;
    warnings_list = {};

    % ---- 参数默认值 ----
    if nargin < 3 || isempty(params)
        params = struct();
    end
    if nargin < 2 || isempty(excel_path)
        excel_path = '';
    end
    if nargin < 4 || isempty(pointlist_in)
        pointlist_in = [];
    end
    if nargin < 5 || isempty(velocitylist_in)
        velocitylist_in = [];
    end
    defaults = struct( ...
        'standoff_distance_mm', 30.0, ...
        'spot_step_size_mm', 2.0, ...
        'subdivide_max_edge', 5.0, ...
        'improve_short_edge', 1.5, ...
        'octree_max_depth', 6.0, ...
        'octree_max_tris', 8.0, ...
        'nozzle_diameter_mm', 6.0, ...
        'traversing_speed_mms', 500.0, ...
        'material_density_gcm3', 7.99, ...
        'particle_velocity_ms', 500.0, ...
        'critical_velocity_ms', 400.0, ...
        'particle_size_um', 25.0, ...
        'layer_height_mm', 2.0, ...
        'scanning_angle_deg', -45.0, ...
        'scanning_step_mm', 2.0, ...
        'edge_step_size_mm', 2.0, ...
        'tilt_angle_deg', 60.0, ...
        'buffer_additive_mm', 2.0, ...
        'buffer_repairing_mm', 0.0, ...
        'link_path_free_dist_mm', 20.0, ...
        'obstacle_resolution_mm', 2.0, ...
        'base_plane', 5.0, ...
        'max_layers', 5.0, ...
        'num_layers', 3.0, ...
        'request_id', '', ...
        'preview_fps', 8.0, ...
        'preview_max_triangles', 1500.0);
    params = complete_struct(params, defaults);

    % ---- 初始化输出结构体 ----
    result = struct();
    result.mesh = zeros(0, 9);
    result.substrate_triangles = zeros(0, 9);
    result.layer_profiles = zeros(0, 4);
    result.particle_distribution = struct( ...
        'px', zeros(0,1), 'py', zeros(0,1), ...
        'vx', zeros(0,1), 'vy', zeros(0,1), 'vz', zeros(0,1), ...
        'vcr', zeros(0,1), 'dep_efficiency', 0.0, ...
        'diameter', zeros(0,1), 'temperature', zeros(0,1));
    result.uniformity = 0.78;
    result.estimated_mass_g = 0.0;
    result.estimated_time_s = 0.0;
    result.predicted_volume_mm3 = 0.0;
    result.warnings = warnings_list;
    result.compute_time_s = 0.0;
    result.waypoint_count = 0;

    % ---- 1. 读取 STL ----
    assert_not_cancelled(params.request_id, 'before STL loading');
    if ~exist(stl_path, 'file')
        result.warnings = {'STL file not found'};
        result.compute_time_s = toc(t0);
        return;
    end
    triangles = read_STLfile(stl_path);
    substrate_triangles = triangles;

    % ---- 2. 三角形细分与短边优化 ----
    assert_not_cancelled(params.request_id, 'before mesh preprocessing');
    triangles = recursiveSubdivide(triangles, params.subdivide_max_edge);
    triangles = improveShortEdges(triangles, [], params.improve_short_edge);

    % ---- 3. 粒子拟合（CFD 数据） ----
    assert_not_cancelled(params.request_id, 'before particle fitting');
    if isempty(excel_path)
        % 自动查找 CFD Excel 文件（profile_prediction 目录已在 matlab_bridge_server.m 中 addpath）
        candidate = fullfile(pwd, 'profile_prediction', 'substrate-surface.xlsx');
        if exist(candidate, 'file')
            excel_path = candidate;
        else
            % 尝试在 path 上搜索
            p = which('substrate-surface.xlsx');
            if ~isempty(p)
                excel_path = p;
            end
        end
    end

    rays_origins = zeros(0, 3);
    rays_directions = zeros(0, 3);
    rays_speeds = zeros(0, 1);
    rays_possiLengths = zeros(0, 1);
    rays_Vcr = zeros(0, 1);
    rays_indices = zeros(0, 1);
    length_threshold = params.improve_short_edge;
    dp_fitting = zeros(0, 1);
    Tp_fitting = zeros(0, 1);

    if ~isempty(excel_path) && exist(excel_path, 'file')
        try
            [rays_indices, rays_origins, rays_directions, rays_speeds, ...
             rays_possiLengths, rays_Vcr, length_threshold, ~] = ...
                particleFitting(excel_path, params.standoff_distance_mm);
            % 读取粒径与温度分布（用于颗粒分布输出）
            [dp_fitting, Tp_fitting] = read_particle_props(excel_path, ...
                rays_origins, rays_directions, rays_speeds);
        catch me
            warnings_list{end+1} = sprintf('particleFitting failed: %s', me.message);
        end
    else
        warnings_list{end+1} = 'CFD Excel file not found, particle distribution will be empty';
    end

    % ---- 4. 路径规划（若未提供预计算航点，则内部调用 run_path_planning） ----
    assert_not_cancelled(params.request_id, 'before path planning');
    if ~isempty(pointlist_in)
        % 使用预计算的航点（来自 MATLABPipeline，避免重复计算）
        pointlist = pointlist_in;
        if ~isempty(velocitylist_in)
            velocitylist = velocitylist_in;
            feed_rates = velocity_to_numeric(velocitylist_in, params.traversing_speed_mms);
        else
            feed_rates = zeros(size(pointlist, 1), 1);
            feed_rates(:) = params.traversing_speed_mms;
            velocitylist = derive_velocitylist(feed_rates, params.traversing_speed_mms);
        end
        % 层号由 Z 值反推
        layer_indices = derive_layer_indices_from_z(pointlist, params.base_plane);
    else
        % 内部调用路径规划
        [pointlist, feed_rates, layer_indices, ~] = ...
            run_path_planning(stl_path, params);
        velocitylist = derive_velocitylist(feed_rates, params.traversing_speed_mms);
    end

    if isempty(pointlist) || size(pointlist, 1) == 0
        warnings_list{end+1} = 'Path planning returned empty waypoints';
        result.mesh = triangles;
        result.substrate_triangles = substrate_triangles;
        result.warnings = warnings_list;
        result.compute_time_s = toc(t0);
        result.waypoint_count = 0;
        return;
    end

    % ---- 5. 喷斑插值 ----
    assert_not_cancelled(params.request_id, 'before spot interpolation');
    ReferencePoint = zeros(1, 6);
    if ~isempty(rays_origins)
        spotsList = spotInterp(ReferencePoint, pointlist, velocitylist, params.spot_step_size_mm);
    else
        spotsList = zeros(0, 7);
        warnings_list{end+1} = 'No rays data, skipping deposition loop';
    end

    if ~isempty(spotsList)
        spot_layer_indices = derive_layer_indices_from_z(spotsList, params.base_plane);
    else
        spot_layer_indices = zeros(0, 1);
    end

    % ---- 6. 逐点形貌预测 ----
    steps = size(spotsList, 1);
    prog_start_time = tic;
    last_publish_s = -inf;
    preview_interval_s = 1.0 / max(double(params.preview_fps), 1.0);
    total_progress_layers = max([spot_layer_indices; 1]);
    if steps > 0
        for i = 1:steps
            assert_not_cancelled(params.request_id, ...
                sprintf('before morphology step %d/%d', i, steps));
            [moveRays_origins, moveRays_directions, nozzleOrientation, Coef_THK] = ...
                rayMove(spotsList(i, :), rays_origins, rays_directions);

            trisOctree = buildOctree(triangles, params.octree_max_depth, params.octree_max_tris);
            tri_candidates = batchOctreeFilter(trisOctree, moveRays_origins, moveRays_directions);

            [intersected_ray_ids, intersected_tri_ids, intersection_points] = ...
                ray_triangle_intersection(rays_indices, moveRays_origins, ...
                    moveRays_directions, triangles, tri_candidates);

            [removedFacetsIdx, ~, raysCluster, boundaryVerticesCluster, C] = ...
                classifyRemovedTriangles(triangles, intersected_tri_ids, ...
                    nozzleOrientation, intersected_ray_ids);

            [oldTriangles, newTriangles] = profilePredict( ...
                triangles, removedFacetsIdx, raysCluster, intersected_tri_ids, ...
                intersection_points, boundaryVerticesCluster, nozzleOrientation, ...
                moveRays_origins, moveRays_directions, rays_speeds, rays_possiLengths, ...
                rays_Vcr, Coef_THK, C, length_threshold);

            triangles = [oldTriangles; newTriangles];

            % ---- 限帧完整快照：预览可覆盖，层末高精度帧可靠 ----
            elapsed_val = toc(prog_start_time);
            cur_layer = spot_layer_indices(i);
            is_layer_end = i == steps || spot_layer_indices(i + 1) ~= cur_layer;
            should_publish_preview = (elapsed_val - last_publish_s) >= preview_interval_s;
            if is_layer_end || should_publish_preview
                if is_layer_end
                    mesh_to_publish = triangles;
                    frame_kind = int32(2);  % MESH_FULL_RESOLUTION_SNAPSHOT
                    event_type = int32(2);  % PROGRESS_TOPO_LAYER_READY
                    reliable_frame = true;
                else
                    mesh_to_publish = select_preview_mesh( ...
                        triangles, params.preview_max_triangles);
                    frame_kind = int32(1);  % MESH_PREVIEW_SNAPSHOT
                    event_type = int32(1);  % PROGRESS_TOPO_SNAPSHOT
                    reliable_frame = false;
                end
                publish_topography_snapshot( ...
                    params.request_id, event_type, frame_kind, ...
                    cur_layer, total_progress_layers, ...
                    0.35 + 0.65 * i / steps, i, steps, ...
                    mesh_to_publish, triangles, substrate_triangles, ...
                    elapsed_val, reliable_frame);
                last_publish_s = elapsed_val;
            end
        end
    end

    % ---- 7. 计算输出指标 ----
    result.mesh = triangles;
    result.substrate_triangles = substrate_triangles;
    result.waypoint_count = size(pointlist, 1);

    % 逐层轮廓
    result.layer_profiles = compute_layer_profiles( ...
        triangles, substrate_triangles, layer_indices, params);

    % 颗粒分布
    if ~isempty(rays_origins)
        vcr_flag = (rays_speeds >= rays_Vcr);
        dep_eff = mean(vcr_flag);
        if isempty(dep_eff)
            dep_eff = 0.0;
        end
        result.particle_distribution = struct( ...
            'px', rays_origins(:, 1), ...
            'py', rays_origins(:, 2), ...
            'vx', rays_directions(:, 1) .* rays_speeds, ...
            'vy', rays_directions(:, 2) .* rays_speeds, ...
            'vz', rays_directions(:, 3) .* rays_speeds, ...
            'vcr', double(vcr_flag), ...
            'dep_efficiency', double(dep_eff), ...
            'diameter', dp_fitting, ...
            'temperature', Tp_fitting);
    end

    % 均匀性评分
    result.uniformity = compute_uniformity(triangles, substrate_triangles);

    % 填充体积与质量
    vol_mm3 = compute_deposition_volume(triangles, substrate_triangles);
    result.predicted_volume_mm3 = vol_mm3;
    result.estimated_mass_g = vol_mm3 * params.material_density_gcm3 * 1e-3;

    % 修复耗时
    path_length_mm = compute_path_length(pointlist);
    if params.traversing_speed_mms > 0
        result.estimated_time_s = path_length_mm / params.traversing_speed_mms;
    else
        result.estimated_time_s = 0.0;
    end

    result.warnings = warnings_list;
    result.compute_time_s = toc(t0);
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

function cancelled = is_cancel_requested(request_id)
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
        error('CSAM:Cancelled', 'Profile prediction cancelled %s', checkpoint);
    end
end

function preview = select_preview_mesh(triangles, max_triangles)
% 使用稳定步长抽样，避免每帧运行昂贵的通用 mesh decimation。
    n = size(triangles, 1);
    limit = max(100, round(double(max_triangles)));
    if n <= limit
        preview = triangles;
        return;
    end
    stride = ceil(n / limit);
    preview = triangles(1:stride:end, :);
end

function publish_topography_snapshot(request_id, event_type, frame_kind, ...
                                     layer_idx, total_layers, progress_value, ...
                                     step_idx, total_steps, mesh_payload, ...
                                     full_mesh, substrate_mesh, elapsed_s, reliable)
    persistent warned_publish_failure;
    if isempty(warned_publish_failure)
        warned_publish_failure = false;
    end
    if isempty(request_id)
        return;
    end

    z_values = [full_mesh(:, 3); full_mesh(:, 6); full_mesh(:, 9)];
    substrate_z = [substrate_mesh(:, 3); substrate_mesh(:, 6); substrate_mesh(:, 9)];
    z_base = max(substrate_z);
    deposited_height = max(z_values - z_base, 0.0);
    max_height = max(deposited_height);
    avg_height = mean(deposited_height);

    try
        py.repair_app.bridge.progress_publisher.publish_progress(pyargs( ...
            'request_id', char(request_id), ...
            'stage', int32(3), ...
            'event_type', event_type, ...
            'mesh_frame_kind', frame_kind, ...
            'layer_index', int32(layer_idx), ...
            'total_layers', int32(total_layers), ...
            'progress', double(progress_value), ...
            'message', sprintf('Morphology layer %d/%d step %d/%d', ...
                               layer_idx, total_layers, step_idx, total_steps), ...
            'layer_max_height', double(max_height), ...
            'layer_avg_height', double(avg_height), ...
            'layer_dep_eff', double(step_idx / max(total_steps, 1)), ...
            'mesh_triangles', mesh_payload, ...
            'elapsed_s', double(elapsed_s), ...
            'reliable', logical(reliable)));
        warned_publish_failure = false;
    catch me
        if ~warned_publish_failure
            warning('CSAM:ProgressPublishFailed', ...
                'Failed to publish morphology snapshot: %s', me.message);
            warned_publish_failure = true;
        end
    end
end


function velocitylist = derive_velocitylist(feed_rates, default_speed)
% 由数值进给速度反推 ABB 速度字符串
%   default_speed * 0.6 -> "velocity_edge"
%   default_speed * 1.2 -> "velocity_link"
%   其他                -> "velocity_infill"
    n = numel(feed_rates);
    velocitylist = strings(n, 1);
    for i = 1:n
        if abs(feed_rates(i) - default_speed * 0.6) < 1e-3
            velocitylist(i) = "velocity_edge";
        elseif abs(feed_rates(i) - default_speed * 1.2) < 1e-3
            velocitylist(i) = "velocity_link";
        else
            velocitylist(i) = "velocity_infill";
        end
    end
end


function [dp_out, Tp_out] = read_particle_props(excelFile, rays_origins, rays_directions, rays_speeds)
% 从 CFD Excel 读取粒径与温度，拟合到与 rays 相同的网格
% 输出：dp_out (um), Tp_out (K)，与 rays_origins 行数一致
    n_rays = size(rays_origins, 1);
    dp_out = zeros(n_rays, 1);
    Tp_out = zeros(n_rays, 1);

    if n_rays == 0
        return;
    end

    try
        x = 1e+3 * 2 * readmatrix(excelFile, 'Range', 'B3:B4362');
        y = 1e+3 * 2 * readmatrix(excelFile, 'Range', 'C3:C4362');
        dp = 1e+6 * readmatrix(excelFile, 'Range', 'H3:H4362');
        Tp = readmatrix(excelFile, 'Range', 'I3:I4362');

        % 用 rays_origins 的 XY 坐标查表
        dp_out = interp2(x, y, dp, rays_origins(:, 1), rays_origins(:, 2), 'linear', 0);
        Tp_out = interp2(x, y, Tp, rays_origins(:, 1), rays_origins(:, 2), 'linear', 300);

        % 去除 NaN
        dp_out(isnan(dp_out)) = 25.0;
        Tp_out(isnan(Tp_out)) = 450.0;
    catch
        % 读取失败时用默认值
        dp_out(:) = 25.0;
        Tp_out(:) = 450.0;
    end
end


function profiles = compute_layer_profiles(triangles, substrate_triangles, layer_indices, params)
% 计算逐层沉积轮廓
% 输出：L×4 [layer_idx, max_height_mm, avg_height_mm, dep_eff]
    profiles = zeros(0, 4);
    if isempty(triangles) || isempty(substrate_triangles)
        return;
    end

    % 基体最高 Z
    sub_z = [substrate_triangles(:, 3); substrate_triangles(:, 6); substrate_triangles(:, 9)];
    z_base = max(sub_z);

    % 沉积表面最高 Z
    tri_z = [triangles(:, 3); triangles(:, 6); triangles(:, 9)];
    z_max = max(tri_z);
    z_min = min(tri_z);

    % 总沉积高度
    total_height = max(z_max - z_base, 0.0);
    if total_height < 1e-6
        return;
    end

    % 按层数分割
    layer_count = max(1, round(params.num_layers));
    dep_eff_base = 0.7;

    for li = 1:layer_count
        z_lo = z_base + (li - 1) * total_height / layer_count;
        z_hi = z_base + li * total_height / layer_count;

        % 统计该层内的三角形顶点
        layer_z = tri_z(tri_z >= z_lo & tri_z <= z_hi);
        if isempty(layer_z)
            continue;
        end

        max_h = max(layer_z) - z_base;
        avg_h = mean(layer_z) - z_base;
        dep_eff = max(dep_eff_base * (1.0 - 0.02 * (li - 1)), 0.3);

        profiles(end+1, :) = [li, max_h, avg_h, dep_eff];
    end
end


function score = compute_uniformity(triangles, substrate_triangles)
% 由沉积表面 Z 高度变异系数派生均匀性评分 [0, 1]
    if isempty(triangles) || isempty(substrate_triangles)
        score = 0.78;
        return;
    end

    sub_z = triangles_triangles_z(substrate_triangles);
    z_base = max(sub_z);

    tri_z = triangles_triangles_z(triangles);
    dep_z = tri_z(tri_z > z_base + 1e-6);

    if numel(dep_z) < 8
        score = 0.78;
        return;
    end

    m = mean(dep_z);
    s = std(dep_z);
    if m < 1e-6
        score = 0.78;
        return;
    end

    cv = s / m;
    score = max(min(1.0 - cv / 0.6, 1.0), 0.5);
end


function z = triangles_triangles_z(triangles)
% 提取所有三角形顶点的 Z 坐标
    z = [triangles(:, 3); triangles(:, 6); triangles(:, 9)];
end


function vol_mm3 = compute_deposition_volume(triangles, substrate_triangles)
% 估算沉积体积 = 最终网格体积 - 基体网格体积
    if isempty(triangles)
        vol_mm3 = 0.0;
        return;
    end

    vol_final = mesh_volume(triangles);
    vol_sub = mesh_volume(substrate_triangles);
    vol_mm3 = max(vol_final - vol_sub, 0.0);
end


function vol = mesh_volume(triangles)
% 由三角形网格估算体积（有符号体积的绝对值）
    n = size(triangles, 1);
    if n == 0
        vol = 0.0;
        return;
    end

    v0 = triangles(:, 1:3);
    v1 = triangles(:, 4:6);
    v2 = triangles(:, 7:9);

    % 有符号体积 = sum(dot(v0, cross(v1, v2))) / 6
    cross_v1v2 = cross(v1, v2, 2);
    signed_vol = sum(sum(v0 .* cross_v1v2, 2)) / 6;
    vol = abs(signed_vol);
end


function path_len = compute_path_length(pointlist)
% 计算航点路径总长度
    n = size(pointlist, 1);
    if n < 2
        path_len = 0.0;
        return;
    end
    diffs = diff(pointlist(:, 1:3), 1, 1);
    path_len = sum(sqrt(sum(diffs.^2, 2)));
end


function feed_rates = velocity_to_numeric(velocitylist, default_speed)
% 将 ABB 速度字符串转为数值 (mm/s)（与 run_path_planning 中一致）
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


function layer_indices = derive_layer_indices_from_z(pointlist, base_plane)
% 由 pointlist 的 Z 值反推层号（简化版，用于预计算航点场景）
    n = size(pointlist, 1);
    z_vals = pointlist(:, 3);
    if n == 0
        layer_indices = zeros(0, 1);
        return;
    end
    % 按 Z 值排序，每 base_plane/2 高度为一层
    z_min = min(z_vals);
    z_max = max(z_vals);
    z_range = max(z_max - z_min, 1e-6);
    n_layers = max(1, round(z_range / 2.0));
    layer_indices = zeros(n, 1);
    for i = 1:n
        layer_indices(i) = max(1, ceil((z_vals(i) - z_min) / z_range * n_layers));
    end
end
