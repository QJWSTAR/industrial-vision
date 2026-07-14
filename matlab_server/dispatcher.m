function resp_env = dispatcher(env, ctx)
%DISPATCHER  Route one envelope to its handler and build the response envelope.
%
%   resp_env = dispatcher(env, ctx)
%
%   env  : decoded envelope struct (request_id, timestamp_ms, message_type,
%          protocol_ver, payload)
%   ctx  : server context struct with fields:
%            cfg        config struct
%            reg        registry instance
%            lc         lifecycle instance
%            shutdown   function handle () -> logical (true when draining)
%
%   Handles every message type defined in protocol v3.0:
%       ALGORITHM_REQUEST   -> invoke algorithm (crash-guarded, timed)
%       HEARTBEAT           -> Pong
%       HEALTH_CHECK        -> HealthStatus
%       LIST_ALGORITHMS     -> ListAlgorithmsResponse
%       VERSION_NEGOTIATE   -> VersionResult
%       CANCELLATION        -> ack (no-op; single-threaded server)
%       SHUTDOWN_REQUEST    -> ShutdownAck (signals the server to stop)
%       anything else       -> AlgorithmResponse UNKNOWN
%
%   The dispatcher NEVER throws: every branch is wrapped so a single bad
%   request cannot take the server down. Errors are translated into a
%   well-formed AlgorithmResponse with an appropriate Status.

    reqId = '';
    if isstruct(env) && isfield(env, 'request_id')
        reqId = char(env.request_id);
    end
    msgType = '';
    if isstruct(env) && isfield(env, 'message_type')
        msgType = char(env.message_type);
    end
    if isempty(msgType)
        msgType = 'UNKNOWN';
    end

    try
        switch upper(msgType)
            case 'ALGORITHM_REQUEST'
                resp_env = handle_algorithm(env, ctx, reqId);
            case 'HEARTBEAT'
                pong = heartbeat(env, ctx.lc);
                resp_env = envelope(reqId, 'PONG', ctx.cfg.protocol_ver, pong);
            case 'HEALTH_CHECK'
                hs = health(ctx.cfg, ctx.lc, ctx.reg);
                resp_env = envelope(reqId, 'HEALTH_STATUS', ctx.cfg.protocol_ver, hs);
            case {'LIST_ALGORITHMS', 'LIST_ALGORITHMS_REQUEST'}
                cat = '';
                if isfield(env,'payload') && isfield(env.payload,'category')
                    cat = char(env.payload.category);
                end
                md = ctx.reg.list_metadata(cat);
                resp_env = envelope(reqId, 'LIST_ALGORITHMS_RESPONSE', ...
                    ctx.cfg.protocol_ver, struct('algorithms', md));
            case 'VERSION_NEGOTIATE'
                vr = struct();
                vr.server_protocol     = ctx.cfg.protocol_ver;
                vr.server_app          = ctx.cfg.server_version;
                vr.protocol_compatible = true;
                vr.available_algorithms = ctx.reg.list();
                vr.algorithm_count     = int32(ctx.reg.count());
                resp_env = envelope(reqId, 'VERSION_RESULT', ctx.cfg.protocol_ver, vr);
            case 'CANCELLATION'
                % Single-threaded server: an in-flight request cannot be
                % preempted. Acknowledge so the client can move on.
                ack = struct('request_id', reqId, 'acknowledged', true);
                resp_env = envelope(reqId, 'CANCELLATION', ctx.cfg.protocol_ver, ack);
            case {'SHUTDOWN_REQUEST', 'SHUTDOWN'}
                resp_env = handle_shutdown(env, ctx, reqId);
            otherwise
                resp_env = error_envelope(reqId, ctx.cfg.protocol_ver, ...
                    'UNKNOWN', '', sprintf('Unsupported message_type: %s', msgType));
        end
    catch err
        resp_env = error_envelope(reqId, ctx.cfg.protocol_ver, ...
            'ERR_ALGORITHM', err.identifier, err.message);
        try, logger('error', 'dispatcher.fatal', reqId, ...
            struct('error_id', err.identifier, 'message', err.message)); catch, end
    end
end

% ============================================================
% ALGORITHM_REQUEST
% ============================================================

function resp_env = handle_algorithm(env, ctx, reqId)
    payload = get_payload(env);
    algoName = '';
    if isfield(payload, 'algorithm_name'), algoName = char(payload.algorithm_name); end
    algoVer  = '';
    if isfield(payload, 'algorithm_ver'), algoVer = char(payload.algorithm_ver); end

    params  = struct();
    inputs  = struct();
    if isfield(payload, 'params') && ~isempty(payload.params), params = payload.params; end
    if isfield(payload, 'inputs') && ~isempty(payload.inputs), inputs = payload.inputs; end

    [desc, found] = ctx.reg.lookup(algoName, algoVer);
    if ~found
        resp_env = error_envelope(reqId, ctx.cfg.protocol_ver, ...
            'ERR_NOT_FOUND', 'algorithm_not_found', ...
            sprintf('Algorithm not registered: %s', algoName));
        try, ctx.lc.record_request_end(false); catch, end
        return;
    end

    % dependency (toolbox) check
    [depOk, depMsg] = check_dependencies(desc);
    if ~depOk
        resp_env = error_envelope(reqId, ctx.cfg.protocol_ver, ...
            'ERR_DEPS', 'missing_toolbox', depMsg);
        try, ctx.lc.record_request_end(false); catch, end
        return;
    end

    try, ctx.lc.record_request_start(); catch, end
    t0 = tic;

    % crash_guard calls fn() with zero args; the closure captures
    % params/inputs so the algorithm receives them correctly.
    cg = ctx.lc.crash_guard(@() desc.fn_handle(params, inputs), reqId);

    elapsed = int64(round(toc(t0) * 1000));
    try, ctx.lc.record_request_end(cg.ok); catch, end

    if cg.ok
        r = struct();
        if isfield(cg.result, 'results'),   r.results   = cg.result.results;   else, r.results   = struct(); end
        if isfield(cg.result, 'artifacts'), r.artifacts = cg.result.artifacts; else, r.artifacts = struct(); end
        resp = struct();
        resp.status          = 'OK';
        resp.compute_time_ms = elapsed;
        resp.results         = r.results;
        resp.artifacts       = r.artifacts;
        resp.algorithm_ver   = desc.version;
        resp.request_id      = reqId;
        resp_env = envelope(reqId, 'ALGORITHM_RESPONSE', ctx.cfg.protocol_ver, resp);
        try, logger('info', 'request.complete', reqId, ...
            struct('algorithm', algoName, 'status', 'OK', 'ms', elapsed)); catch, end
    else
        resp_env = error_envelope(reqId, ctx.cfg.protocol_ver, ...
            'ERR_ALGORITHM', cg.id, cg.error);
        try, logger('error', 'request.fail', reqId, ...
            struct('algorithm', algoName, 'error_id', cg.id, 'ms', elapsed)); catch, end
    end
end

% ============================================================
% SHUTDOWN
% ============================================================

function resp_env = handle_shutdown(env, ctx, reqId)
    grace = 0;
    if isfield(env, 'payload') && isfield(env.payload, 'grace_period_ms')
        grace = double(env.payload.grace_period_ms);
    end
    % Signal the main loop to stop accepting new work.
    try, ctx.shutdown(); catch, end
    ack = struct();
    ack.accepted          = true;
    ack.pending_count     = int32(ctx.lc.pending_count);
    ack.estimated_drain_ms = int64(grace);
    resp_env = envelope(reqId, 'SHUTDOWN_ACK', ctx.cfg.protocol_ver, ack);
    try, logger('warn', 'shutdown.request', reqId, struct('grace_ms', grace)); catch, end
end

% ============================================================
% helpers
% ============================================================

function p = get_payload(env)
    if isstruct(env) && isfield(env, 'payload') && isstruct(env.payload)
        p = env.payload;
    else
        p = struct();
    end
end

function env = envelope(reqId, msgType, protoVer, payload)
    env = struct();
    env.request_id   = reqId;
    env.timestamp_ms = int64(posix_now_ms());
    env.message_type = msgType;
    env.protocol_ver = protoVer;
    env.payload      = payload;
end

function env = error_envelope(reqId, protoVer, status, errCode, errMsg)
    resp = struct();
    resp.status        = status;
    resp.error_code    = errCode;
    resp.error_message = errMsg;
    resp.results       = struct();
    resp.artifacts     = struct();
    resp.request_id    = reqId;
    env = envelope(reqId, 'ALGORITHM_RESPONSE', protoVer, resp);
end

function [ok, msg] = check_dependencies(desc)
    ok = true; msg = '';
    if ~isfield(desc, 'dependencies') || isempty(desc.dependencies), return; end
    missing = {};
    for k = 1:numel(desc.dependencies)
        tb = desc.dependencies{k};
        avail = false;
        try, avail = license('test', tb) == 1; catch, end
        if ~avail, missing{end+1} = tb; end %#ok<AGROW>
    end
    if ~isempty(missing)
        ok = false;
        msg = sprintf('Missing required toolbox(es): %s', strjoin(missing, ', '));
    end
end

function ts = posix_now_ms()
    ts = round(posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000);
end
