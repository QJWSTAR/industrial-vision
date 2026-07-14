% TEST_RUN_PATH_PLANNING  验证 run_path_planning 接口
% 在 MATLAB 命令行运行：test_run_path_planning
% 验证：STL → model_process → layer_slice → generate_path → 内存返回

clc;
fprintf('===== 测试 run_path_planning =====\n');

% 切换到脚本所在目录
script_dir = fileparts(mfilename('fullpath'));
cd(script_dir);
addpath(script_dir);

% 使用项目自带的 STL 文件
stl_path = fullfile(script_dir, 'substrate.stl');
if ~exist(stl_path, 'file')
    stl_path = fullfile(script_dir, 'target.stl');
end
if ~exist(stl_path, 'file')
    stl_path = fullfile(script_dir, 'part.stl');
end
fprintf('STL 文件: %s\n', stl_path);

% 构造参数
params = struct();
params.base_plane = 5.0;
params.layer_height = 2.0;
params.buffer_additive = 2.0;
params.buffer_repairing = 0.0;
params.scanning_angle = -45.0;
params.scanning_step = 2.0;
params.edge_step_size = 2.0;
params.tilt_angle = 60.0;
params.link_path_free_dist = 20.0;
params.resolution = 2.0;
params.traversing_speed_mms = 500.0;

% 调用
fprintf('调用 run_path_planning...\n');
t0 = tic;
try
    [pointlist, feed_rates, layer_indices, meta_out] = ...
        run_path_planning(stl_path, params);

    fprintf('\n===== 结果 =====\n');
    fprintf('航点数: %d\n', size(pointlist, 1));
    fprintf('pointlist 维度: [%d, %d]\n', size(pointlist, 1), size(pointlist, 2));
    fprintf('feed_rates 维度: [%d, %d]\n', size(feed_rates, 1), size(feed_rates, 2));
    fprintf('layer_indices 维度: [%d, %d]\n', size(layer_indices, 1), size(layer_indices, 2));
    fprintf('计算耗时: %.2f s\n', meta_out.compute_time_s);
    fprintf('层号范围: %d ~ %d\n', min(layer_indices), max(layer_indices));
    fprintf('速度范围: %.1f ~ %.1f\n', min(feed_rates), max(feed_rates));

    % 验证法向量不为全 [0,0,1]（倾角法向生效）
    unique_normals = unique(round(pointlist(:, 4:6), 4), 'rows');
    fprintf('唯一法向量数: %d\n', size(unique_normals, 1));
    if size(unique_normals, 1) > 1
        fprintf('  倾角法向: 已生效\n');
    else
        fprintf('  倾角法向: 未生效（可能只有 infill 路径）\n');
    end

    fprintf('\n===== 测试通过 =====\n');
catch e
    fprintf('\n===== 测试失败 =====\n');
    fprintf('错误: %s\n', e.message);
    fprintf('位置: %s 行 %d\n', e.stack(1).name, e.stack(1).line);
end
