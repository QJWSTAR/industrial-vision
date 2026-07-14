function startup()
%STARTUP  Entry point for the CSAM MATLAB algorithm server.
%
%   Reads configuration from environment variables (see config.m), adds the
%   algorithm directories to the MATLAB path, and starts the server.
%
%   The algorithm directories (路径规划/ and 形貌预测/) have Chinese names
%   that are encoding-sensitive on Windows. To avoid mojibake issues, the
%   directories are located by probing for characteristic .m files rather
%   than hard-coding their names.
%
%   Usage:
%       cd('D:\work\demo\industrial-vision\matlab_server')
%       startup
%
%   Environment variables (all optional - see config.m for defaults):
%     CSAM_MATLAB_BIND            tcp://*:5570
%     CSAM_MATLAB_LOG_DIR         <repo>/logs
%     CSAM_MATLAB_HEARTBEAT_MS    1000
%     CSAM_MATLAB_LOG_LEVEL       info

    serverDir = fileparts(mfilename('fullpath'));
    repoRoot  = fileparts(serverDir);

    % Ensure the server directory itself is on the path so that
    % config, server, dispatcher, etc. are all resolvable.
    addpath(serverDir);

    % Locate and add algorithm directories (encoding-agnostic).
    pathPlanningDir = find_dir_containing(repoRoot, 'layer_slice.m');
    morphologyDir   = find_dir_containing(repoRoot, 'profilePredict.m');

    if ~isempty(pathPlanningDir)
        addpath(pathPlanningDir);
        fprintf('  addpath: %s\n', pathPlanningDir);
    else
        warning('startup:noPathPlanning', ...
            'Path-planning directory not found under %s', repoRoot);
    end
    if ~isempty(morphologyDir)
        addpath(morphologyDir);
        fprintf('  addpath: %s\n', morphologyDir);
    else
        warning('startup:noMorphology', ...
            'Morphology directory not found under %s', repoRoot);
    end

    % Build configuration from environment and start the server.
    cfg = config();
    fprintf('CSAM MATLAB Server starting on %s (port %d), protocol v%s\n', ...
        cfg.bind, cfg.port, cfg.protocol_ver);
    srv = server(cfg);
    srv.run();
end

% ============================================================

function d = find_dir_containing(root, filename)
%FIND_DIR_CONTAINING  Return the first subdirectory of `root` that
%   contains a file named `filename`. Returns '' if not found.
%   This avoids hard-coding Chinese directory names that may be
%   mangled by file-system encoding differences.
    d = '';
    entries = dir(root);
    for i = 1:numel(entries)
        if ~entries(i).isdir, continue; end
        name = entries(i).name;
        if strcmp(name, '.') || strcmp(name, '..'), continue; end
        candidate = fullfile(root, name);
        if exist(fullfile(candidate, filename), 'file')
            d = candidate;
            return;
        end
    end
end
