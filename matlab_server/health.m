function hs = health(cfg, lc, reg)
%HEALTH  Build a HealthStatus struct for HEALTH_CHECK requests.
%
%   hs = health(cfg, lc, reg)
%
%   cfg : server config struct (config())
%   lc  : lifecycle instance
%   reg : registry instance (may be [] when not supplied)
%
%   Returns a struct mirroring the HealthStatus proto:
%       state              'OK' | 'DEGRADED' | 'DOWN'
%       server_version     char
%       matlab_version     char
%       memory_mb          double
%       uptime_s           double
%       pending_reqs       int32
%       toolbox_available  struct of {name -> logical}
%       error_rate_1m      double
%       total_requests     int32
%       last_error_ts      int64
%
%   Toolboxes are probed with license('test', ...). Map_Toolbox is required
%   only by generate_path and profile_predict (polyxpoly); Curve_Fitting_Toolbox
%   is required by particleFitting (fit/fittype). NOTE: containers.Map, graph,
%   conncomp, dfsearch are BASE MATLAB, not Map_Toolbox (H2 correction).
%   When a required toolbox is missing the state degrades to 'DEGRADED'.

    if nargin < 2 || isempty(lc),  lc  = []; end
    if nargin < 3 || isempty(reg), reg = []; end

    stats = [];
    if ~isempty(lc)
        stats = lc.get_stats();
    else
        stats.uptime_s       = 0;
        stats.total_requests = 0;
        stats.error_rate_1m  = 0;
        stats.pending_count  = 0;
        stats.last_error_ts  = 0;
    end

    hs = struct();
    hs.server_version = char(cfg.server_version);
    hs.matlab_version = version;
    hs.memory_mb      = memory_usage_mb();
    hs.uptime_s       = round(stats.uptime_s);
    hs.pending_reqs   = int32(stats.pending_count);
    hs.error_rate_1m  = stats.error_rate_1m;
    hs.total_requests = int32(stats.total_requests);
    hs.last_error_ts  = int64(stats.last_error_ts);

    % ---- toolbox probes ----------------------------------------------
    toolboxes = {'Map_Toolbox', 'Curve_Fitting_Toolbox'};
    hs.toolbox_available = struct();
    all_ok = true;
    for k = 1:numel(toolboxes)
        tb = toolboxes{k};
        ok = false;
        try, ok = license('test', tb) == 1; catch, ok = false; end
        hs.toolbox_available.(tb) = logical(ok);
        if ~ok, all_ok = false; end
    end

    % ---- state derivation --------------------------------------------
    %   DOWN    : never (process is alive to answer)
    %   DEGRADED: a required toolbox missing OR error rate very high
    %   OK      : otherwise
    if ~all_ok
        hs.state = 'DEGRADED';
    elseif stats.error_rate_1m > 0.5 && stats.total_requests > 10
        hs.state = 'DEGRADED';
    else
        hs.state = 'OK';
    end
end

% ============================================================
function mb = memory_usage_mb()
%MEMORY_USAGE_MB  Estimate the MATLAB process RSS in megabytes.
%   Prefers the Java runtime memory metric (always available); falls back
%   to the memmapinfo/diagnostics when the Java call is unavailable.
    mb = 0;
    try
        rt = java.lang.Runtime.getRuntime();
        used = rt.totalMemory() - rt.freeMemory();
        mb = double(used) / (1024 * 1024);
    catch
    end
    if mb <= 0
        try
            info = memory;
            mb = info.MemUsedMATLAB / (1024 * 1024);
        catch
        end
    end
end
