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

    % ---- 共享 MATLAB 引擎会话（供 Python matlab.engine 反向调用）----
    sharedName = getenv('CSAM_MATLAB_SHARED_NAME');
    if isempty(sharedName)
        sharedName = 'matlab_bridge';
    end
    matlab.engine.shareEngine(sharedName);
    fprintf('MATLAB 引擎已共享: "%s"\n', sharedName);

    % ---- addpath 算法目录 ----
    addpath(fullfile(pwd, '形貌预测'));
    addpath(fullfile(pwd, '路径规划'));
    fprintf('算法路径已加载\n');

    % 设置 Python 环境为项目虚拟环境
    venvPython = fullfile(pwd, 'venv', 'Scripts', 'python.exe');
    if exist(venvPython, 'file')
        pyenv('Version', venvPython);
    end
    pe = pyenv;
    fprintf('MATLAB Python 环境: %s (%s)\n', pe.Version, pe.ExecutionMode);

    % 解析地址参数
    if nargin < 1 || isempty(address)
        % 读取环境变量 CSAM_ZMQ_ADDRESS（与 Python 侧统一）
        address = getenv('CSAM_ZMQ_ADDRESS');
        if isempty(address)
            address = 'tcp://127.0.0.1:5555';
        end
    end
    fprintf('绑定地址: %s\n', address);

    % 导入 bridge 模块
    try
        bridgeMod = py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter');
        fprintf('bridge 模块导入成功\n');
    catch e
        fprintf('导入失败: %s\n', e.message);
        return;
    end

    % 创建并启动适配器
    fprintf('========================================\n');
    fprintf('MATLAB Bridge 修复引擎服务启动中...\n');
    fprintf('按 Ctrl+C 停止服务\n');
    fprintf('========================================\n');

    try
        adapter = bridgeMod.MatlabAdapter(address=address);
        adapter.install_signal_handlers();
        adapter.serve();
    catch e
        if contains(e.message, 'KeyboardInterrupt') || contains(e.message, 'interrupt')
            fprintf('\n收到中断信号，服务已停止\n');
        else
            fprintf('服务异常: %s\n', e.message);
        end
    end
end
