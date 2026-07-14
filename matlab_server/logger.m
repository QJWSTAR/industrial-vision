function logger(level, event, req_id, fields)
%LOGGER  Structured JSONL logger for the MATLAB server.
%
%   logger(level, event, req_id, fields)
%
%   level       : 'debug' | 'info' | 'warn' | 'error'
%   event       : short event name, e.g. 'request.start'
%   req_id      : request id (may be '' when not applicable)
%   fields      : struct of extra key/value pairs (optional)
%
%   One JSON object per line is written to stdout AND appended to the daily
%   log file (<log_dir>/matlab_server_<date>.log). The log file path and
%   minimum level are read from the cached config struct kept in a
%   persistent variable; call logger('init', cfg) once at startup to
%   configure it. Messages below the configured level are dropped silently.
%
%   This function is deliberately side-effect free with respect to the base
%   workspace: it never uses `clear` and never throws - a logging failure
%   must not take the server down.

    persistent CFG
    if isempty(CFG)
        % Sensible defaults until init is called.
        CFG = struct('log_dir', '', 'min_level', 20, ...
                     'levels', struct('debug',10,'info',20,'warn',30,'error',40));
    end

    % special control actions
    if strcmp(level, 'init')
        cfg = event;   % second arg carries the config struct
        levels = struct('debug',10,'info',20,'warn',30,'error',40);
        if isfield(cfg, 'log_levels'), levels = cfg.log_levels; end
        minLevel = 20;
        if isfield(cfg, 'log_level') && isfield(levels, cfg.log_level)
            minLevel = levels.(cfg.log_level);
        end
        CFG = struct('log_dir', cfg.log_dir, 'min_level', minLevel, 'levels', levels);
        return;
    end
    if strcmp(level, 'flush')
        return;
    end

    if nargin < 4, fields = struct(); end
    if isempty(fields) || ~isstruct(fields), fields = struct(); end

    lvl = lower(level);
    rank = 20;
    if isfield(CFG.levels, lvl), rank = CFG.levels.(lvl); end
    if rank < CFG.min_level
        return;   % filtered out
    end

    rec = struct();
    rec.ts         = matlab_iso8601_now();
    rec.level      = lvl;
    rec.event      = char(event);
    rec.request_id = char(req_id);
    rec = merge_fields(rec, fields);

    line = jsonencode(rec, 'ConvertInfAndNaN', true);

    % stdout (never let fprintf crash the server)
    try, fprintf('%s\n', line); catch, end

    % file append
    if ~isempty(CFG.log_dir)
        try
            % L1 fix: datestr(now) deprecated in R2025b -> datetime
            % M6 fix: explicit UTF-8 encoding for non-ASCII log content
            fname = fullfile(CFG.log_dir, sprintf('matlab_server_%s.log', ...
                datestr(datetime('now'),'yyyymmdd')));
            fid = fopen(fname, 'a', 'n', 'UTF-8');
            if fid > 0
                fprintf(fid, '%s\n', line);
                fclose(fid);
            end
        catch
            % swallow - logging must never raise
        end
    end
end

% ============================================================
% helpers
% ============================================================

function s = merge_fields(s, extra)
%MERGE_FIELDS  Copy fields from `extra` into `s` without overwriting the
%   reserved keys already present. Empty extra values are skipped so that
%   absent optional fields do not pollute the log line.
    if isempty(extra), return; end
    fns = fieldnames(extra);
    reserved = {'ts','level','event','request_id'};
    for k = 1:numel(fns)
        fn = fns{k};
        if any(strcmp(fn, reserved)), continue; end
        val = extra.(fn);
        if isempty(val), continue; end
        s.(fn) = val;
    end
end

function ts = matlab_iso8601_now()
%MATLAB_ISO8601_NOW  UTC timestamp in ISO-8601 with millisecond precision.
    t = datetime('now', 'TimeZone', 'UTC');
    ts = char(t, 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z''');
end
