function matlab_bridge_server(address)
% MATLAB_BRIDGE_SERVER  使用新通信层启动 MATLAB 修复引擎服务
%
% 用法：
%   matlab_bridge_server                          % 使用默认地址
%   matlab_bridge_server('tcp://127.0.0.1:5555')  % 指定地址
%
% 此脚本通过 pyenv 调用 Python 的 MatlabAdapter 服务端。
% MATLAB 作为进程宿主，负责启动、监控和优雅关闭服务。
% 同时共享 MATLAB 引擎会话，供 Python 侧 matlab.engine.connect_matlab 复用。
%
% Ctrl+C 行为：
%   MATLAB 的 Ctrl+C 会转为 Python KeyboardInterrupt，
%   serve() 在 finally 中清理 ZMQ socket/context，
%   onCleanup 确保共享会话注销与引擎引用释放。

    % ---- 标记 Python 运行在 MATLAB pyenv 内 ----
    % MatlabEngineProxy 检测此变量后跳过 find_matlab，直接 connect_matlab()
    setenv('CSAM_BRIDGE_IN_MATLAB', '1');

    % ---- 共享 MATLAB 引擎会话（供外部 Python 进程 matlab.engine 反向调用）----
    sharedName = getenv('CSAM_MATLAB_SHARED_NAME');
    if isempty(sharedName)
        sharedName = 'matlab_bridge';
    end

    % onCleanup: 无论正常退出还是 Ctrl+C，都注销共享会话
    cleanupObj = onCleanup(@() cleanup_bridge(sharedName));

    try
        matlab.engine.shareEngine(sharedName);
        fprintf('MATLAB engine shared: "%s"\n', sharedName);
    catch ME
        % 可能已经共享过
        if contains(ME.message, 'already') || contains(ME.message, 'shared')
            fprintf('MATLAB engine already shared: "%s"\n', sharedName);
        else
            fprintf('Failed to share engine: %s\n', ME.message);
            return;
        end
    end

    % ---- addpath 算法目录 ----
    addpath(fullfile(pwd, 'path_planning'));
    addpath(fullfile(pwd, 'profile_prediction'));
    fprintf('Algorithm paths loaded\n');

    % 设置 Python 环境为项目虚拟环境
    venvPython = fullfile(pwd, 'venv', 'Scripts', 'python.exe');
    if ~exist(venvPython, 'file')
        venvPython = fullfile(pwd, 'venv', 'bin', 'python');
    end
    if exist(venvPython, 'file')
        pyenv('Version', venvPython);
    end
    pe = pyenv;
    fprintf('MATLAB Python env: %s (%s)\n', pe.Version, pe.ExecutionMode);

    % 解析地址参数
    if nargin < 1 || isempty(address)
        address = getenv('CSAM_ZMQ_ADDRESS');
        if isempty(address)
            address = 'tcp://127.0.0.1:5555';
        end
    end
    fprintf('Bind address: %s\n', address);

    % 导入 bridge 模块
    try
        bridgeMod = py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter');
        fprintf('bridge module imported successfully\n');
    catch e
        fprintf('Import failed: %s\n', e.message);
        return;
    end

    % 创建并启动适配器
    fprintf('========================================\n');
    fprintf('MATLAB Bridge repair engine service starting...\n');
    fprintf('Press Ctrl+C to stop the service\n');
    fprintf('========================================\n');

    adapter = [];
    try
        adapter = bridgeMod.MatlabAdapter(address=address);
        adapter.serve();
    catch e
        if contains(e.message, 'KeyboardInterrupt') || contains(e.message, 'interrupt')
            fprintf('\nCtrl+C interrupt received, service stopped\n');
        else
            fprintf('Service error: %s\n', e.message);
        end
    end

    % 显式调用 shutdown 释放 MATLAB 引擎引用
    if ~isempty(adapter)
        try
            adapter.shutdown();
        catch
            % shutdown 可能已被 _cleanup 调用过，忽略
        end
    end
end

function cleanup_bridge(sharedName)
    % onCleanup 回调：注销共享会话，确保下次启动不残留
    try
        if matlab.engine.isEngineShared()
            matlab.engine.unshareEngine();
            fprintf('[cleanup] Unregistered shared session: "%s"\n', sharedName);
        end
    catch
        % 忽略清理异常
    end
    % 清除环境变量标记
    setenv('CSAM_BRIDGE_IN_MATLAB', '');
end
