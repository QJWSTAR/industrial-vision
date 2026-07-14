function cfg = config()
%CONFIG  Build the MATLAB server configuration struct.
%
%   cfg = config() returns a struct with all runtime configuration. Every
%   value can be overridden through an environment variable so that the same
%   code runs in development and production without edits.
%
%   Transport: TCP via java.net.ServerSocket (no ZMQ dependency in MATLAB).
%   The CSAM_MATLAB_BIND address is parsed into a host/port pair. The host is
%   informational (ServerSocket binds to all interfaces when given '*'); only
%   the port is used by the listener.
%
%   Environment variables:
%     CSAM_MATLAB_BIND          tcp://*:5570   (default)
%     CSAM_MATLAB_LOG_DIR       <repo>/logs    (default)
%     CSAM_MATLAB_HEARTBEAT_MS  1000           (default)
%     CSAM_MATLAB_MAX_REQ_BYTES 67108864       (64 MB default)
%     CSAM_MATLAB_CLEANUP_INTERVAL 50          (requests between cleanups)
%     CSAM_MATLAB_MEM_THRESHOLD_MB 4096        (pack memory above this)
%     CSAM_MATLAB_LOG_LEVEL     info           (debug/info/warn/error)

    serverDir = fileparts(mfilename('fullpath'));
    repoRoot  = fileparts(serverDir);

    % ---- bind address -> host/port -----------------------------------
    bind = getenv_def('CSAM_MATLAB_BIND', 'tcp://*:5570');
    [host, port] = parse_bind(bind);

    % ---- log directory -----------------------------------------------
    logDir = getenv_def('CSAM_MATLAB_LOG_DIR', fullfile(repoRoot, 'logs'));
    if ~isempty(logDir) && ~exist(logDir, 'dir')
        try
            mkdir(logDir);
        catch
            % fall back to a temp dir if the configured path is unwritable
            logDir = tempdir;
        end
    end

    cfg = struct();
    cfg.bind                 = bind;
    cfg.host                 = host;
    cfg.port                 = port;
    cfg.log_dir              = logDir;
    cfg.log_level            = lower(getenv_def('CSAM_MATLAB_LOG_LEVEL', 'info'));
    cfg.heartbeat_ms         = getenv_int('CSAM_MATLAB_HEARTBEAT_MS', 1000);
    cfg.max_request_bytes    = getenv_int('CSAM_MATLAB_MAX_REQ_BYTES', 64*1024*1024);
    cfg.cleanup_interval     = getenv_int('CSAM_MATLAB_CLEANUP_INTERVAL', 50);
    cfg.memory_threshold_mb  = getenv_int('CSAM_MATLAB_MEM_THRESHOLD_MB', 4096);
    cfg.server_version       = 'matlab-server-3.0.0';
    cfg.protocol_ver         = '3.0';
    cfg.poll_timeout_ms      = 200;          % accept() interrupt window
    cfg.repo_root            = repoRoot;
    cfg.server_dir           = serverDir;

    % ---- log-level rank for filtering --------------------------------
    cfg.log_levels = struct( ...
        'debug', 10, 'info', 20, 'warn', 30, 'error', 40);
end

% ============================================================
% helpers
% ============================================================

function v = getenv_def(name, default)
    v = getenv(name);
    if isempty(v), v = default; end
end

function v = getenv_int(name, default)
    s = getenv(name);
    if isempty(s)
        v = default;
    else
        v = sscanf(s, '%d');
        if isempty(v), v = default; end
    end
end

function [host, port] = parse_bind(bind)
%PARSE_BIND  Parse 'tcp://host:port' into host (char) and port (double).
%   A host of '*' means listen on all interfaces (translated to '' so that
%   java.net.ServerSocket(port) binds to 0.0.0.0).
    host = '';
    port = 5570;
    s = bind;
    if startsWith(s, 'tcp://'), s = s(7:end); end
    colon = strfind(s, ':');
    if ~isempty(colon)
        host = s(1:colon(end)-1);
        port = sscanf(s(colon(end)+1:end), '%d');
        if isempty(port), port = 5570; end
    end
    if strcmp(host, '*') || strcmp(host, '0.0.0.0')
        host = '';   % bind to all interfaces
    end
end
