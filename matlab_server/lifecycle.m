classdef lifecycle < handle
%LIFECYCLE  Lifecycle / stats manager for the MATLAB server.
%
%   Tracks counters that drive health reporting and graceful shutdown:
%       start_time       datetime when the manager was created
%       total_requests   cumulative request count
%       error_count      cumulative error count
%       last_error_ts    ms timestamp of the most recent error (0 if none)
%       pending_count    requests currently in flight
%       recent_results   rolling buffer of recent ok/error flags (1m window)
%
%   Methods:
%       record_request_start()         -> increment pending
%       record_request_end(ok)         -> decrement pending, tally result
%       get_stats()                    -> struct snapshot
%       error_rate_1m()                -> fraction of errors in last window
%       crash_guard(fn, req_id)        -> try/catch wrapper that logs and
%                                         returns a struct {ok,error,err_id}
%                                         instead of throwing. The server
%                                         must NEVER crash on a bad request.
%
%   This class holds mutable state and therefore derives from handle so all
%   collaborators observe the same counters.

    properties
        start_time
        total_requests = 0
        error_count    = 0
        last_error_ts  = 0
        pending_count  = 0
    end

    properties (Access = private)
        recent_window = []      % column vector of {0,1} flags (1=error)
        window_capacity = 2000  % cap the rolling buffer memory
    end

    methods
        function obj = lifecycle()
            obj.start_time = datetime('now', 'TimeZone', 'UTC');
        end

        function record_request_start(obj)
            %RECORD_REQUEST_START  Mark a new request as in-flight.
            obj.pending_count = obj.pending_count + 1;
            obj.total_requests = obj.total_requests + 1;
        end

        function record_request_end(obj, ok)
            %RECORD_REQUEST_END  Mark a request complete.
            %   ok is logical true for success, false for any error.
            if obj.pending_count > 0
                obj.pending_count = obj.pending_count - 1;
            end
            if ~ok
                obj.error_count = obj.error_count + 1;
                obj.last_error_ts = posix_now_ms();
            end
            obj.push_result(~ok);
        end

        function s = get_stats(obj)
            %GET_STATS  Snapshot of all counters for health reporting.
            s.start_time      = obj.start_time;
            s.uptime_s        = seconds(datetime('now','TimeZone','UTC') - obj.start_time);
            s.total_requests  = obj.total_requests;
            s.error_count     = obj.error_count;
            s.last_error_ts   = obj.last_error_ts;
            s.pending_count   = obj.pending_count;
            s.error_rate_1m   = obj.error_rate_1m();
        end

        function r = error_rate_1m(obj)
            %ERROR_RATE_1M  Fraction of errors in the recent result window.
            if isempty(obj.recent_window)
                r = 0;
            else
                r = sum(obj.recent_window) / numel(obj.recent_window);
            end
        end

        function out = crash_guard(obj, fn, req_id)
            %CRASH_GUARD  Execute fn() inside try/catch.
            %   Never throws: returns struct with fields:
            %       ok      logical
            %       result  fn output (when ok)
            %       error   char message (when not ok)
            %       id      char error identifier (when not ok)
            %   Any error is logged via logger() so the operator has a
            %   record, but the caller decides how to translate it into a
            %   protocol response.
            if nargin < 3, req_id = ''; end
            out = struct('ok', false, 'result', [], 'error', '', 'id', '');
            try
                out.result = fn();
                out.ok = true;
            catch err
                out.ok    = false;
                out.error = err.message;
                out.id    = err.identifier;
                f = struct('error_id', err.identifier, 'stack', format_stack(err));
                try, logger('error', 'request.crash', req_id, f); catch, end
            end
        end
    end

    methods (Access = private)
        function push_result(obj, is_error)
            if numel(obj.recent_window) >= obj.window_capacity
                obj.recent_window(1) = [];
            end
            obj.recent_window(end+1, 1) = is_error;
        end
    end
end

% ============================================================
% free helpers
% ============================================================

function ts = posix_now_ms()
%POSIX_NOW_MS  Current UTC time in milliseconds since the Unix epoch.
    ts = round(posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000);
end

function s = format_stack(err)
%FORMAT_STACK  Reduce an MException stack to a single semicolon-joined line.
    if isempty(err.stack)
        s = '';
        return;
    end
    parts = cell(numel(err.stack), 1);
    for k = 1:numel(err.stack)
        parts{k} = sprintf('%s:%d (%s)', err.stack(k).file, ...
            err.stack(k).line, err.stack(k).name);
    end
    s = strjoin(parts, ' ; ');
end
