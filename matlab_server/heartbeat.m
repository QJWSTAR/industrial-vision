function pong = heartbeat(env, lc)
%HEARTBEAT  Build a Pong response for HEARTBEAT messages.
%
%   pong = heartbeat(env, lc)
%
%   env : the incoming envelope struct (carries request_id + client_ts_ms)
%   lc  : lifecycle instance (for the pending count)
%
%   Returns a struct mirroring the Pong proto:
%       request_id   char   (echoed from the heartbeat)
%       server_ts_ms int64  (server UTC time in ms)
%       pending      int32  (currently in-flight requests)

    if nargin < 2 || isempty(lc), lc = []; end

    reqId = '';
    if isstruct(env) && isfield(env, 'request_id')
        reqId = char(env.request_id);
    end

    pending = 0;
    if ~isempty(lc)
        try, pending = lc.pending_count; catch, end
    end

    pong = struct();
    pong.request_id   = reqId;
    pong.server_ts_ms = int64(posix_now_ms());
    pong.pending      = int32(pending);
end

function ts = posix_now_ms()
    ts = round(posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000);
end
