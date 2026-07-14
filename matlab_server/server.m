classdef server < handle
%SERVER  Main MATLAB algorithm server (Protocol v3.0).
%
%   A long-running MATLAB process that hosts algorithm functions and serves
%   them over a JSON-over-TCP wire format mirroring Protocol Buffers v3.0.
%   Uses java.net.ServerSocket (no ZMQ dependency, always available via the
%   JVM bundled with MATLAB) with 4-byte big-endian length-prefixed framing.
%
%   Wire format:
%       [4-byte big-endian uint32 length N][N bytes UTF-8 JSON]
%
%   The JSON payload is an Envelope struct with fields:
%       request_id, timestamp_ms, message_type, protocol_ver, payload
%
%   Usage:
%       srv = server();       % uses config() defaults
%       srv.run();            % blocks until SHUTDOWN or stop()
%
%   Methods:
%       run()             - main accept/dispatch loop (blocks)
%       stop()            - signal the loop to exit and close the socket
%       handle_shutdown() - called by the dispatcher on SHUTDOWN_REQUEST
%
%   Safety:
%       - The server NEVER calls `clear all` or `clear` without arguments.
%       - All I/O and algorithm dispatch is wrapped in try/catch so a
%         single bad request or socket error cannot crash the process.
%       - Resource cleanup runs synchronously every N requests (MATLAB is
%         single-threaded; no background timers or threads).

    properties
        cfg            % configuration struct (config.m)
        reg            % registry instance (registry.m)
        lc             % lifecycle instance (lifecycle.m)
        socket = []    % java.net.ServerSocket
        running = false
        request_count = 0
    end

    methods
        function obj = server(cfg)
            %SERVER  Construct the server.
            %   server()        uses config() defaults
            %   server(cfg)     uses the supplied config struct
            if nargin < 1 || isempty(cfg)
                cfg = config();
            end
            obj.cfg = cfg;
            obj.reg = registry();
            register_algorithms(obj.reg);
            obj.lc = lifecycle();
            logger('init', cfg);
        end

        function run(obj)
            %RUN  Main server loop. Blocks until stop() or SHUTDOWN_REQUEST.
            obj.running = true;

            % ---- bind the listener --------------------------------------
            try
                obj.socket = java.net.ServerSocket(int32(obj.cfg.port));
                obj.socket.setSoTimeout(int32(obj.cfg.poll_timeout_ms));
            catch ME
                logger('error', 'server.bind.fail', '', ...
                    struct('port', obj.cfg.port, 'error', ME.message));
                obj.running = false;
                return;
            end

            logger('info', 'server.start', '', ...
                struct('port', obj.cfg.port, ...
                       'version', obj.cfg.server_version, ...
                       'protocol', obj.cfg.protocol_ver, ...
                       'algorithms', obj.reg.count()));

            % ---- accept / dispatch loop ---------------------------------
            while obj.running
                client = [];
                try
                    client = obj.socket.accept();
                catch ME
                    % setSoTimeout makes accept() throw a
                    % SocketTimeoutException every poll_timeout_ms - this
                    % is expected and lets us re-check `running`.
                    if contains(ME.message, 'timed out', 'IgnoreCase', true) || ...
                       contains(ME.message, 'Timeout', 'IgnoreCase', true)
                        continue;
                    end
                    logger('error', 'accept.fail', '', ...
                        struct('error', ME.message));
                    pause(0.05);  % avoid tight error loop
                    continue;
                end

                if isempty(client), continue; end

                % Handle one request. Never let a client error escape.
                try
                    obj.handle_client(client);
                catch ME
                    logger('error', 'client.fail', '', ...
                        struct('error', ME.message));
                end

                % Always close the client socket (one request per connection).
                try, client.close(); catch, end

                % ---- periodic resource cleanup --------------------------
                % MATLAB is single-threaded: cleanup runs synchronously
                % between requests, never on a background thread.
                obj.request_count = obj.request_count + 1;
                if mod(obj.request_count, obj.cfg.cleanup_interval) == 0
                    try
                        info = resource_cleanup(obj.cfg);
                        logger('debug', 'cleanup.done', '', ...
                            struct('before_mb', info.mem_before_mb, ...
                                   'after_mb',  info.mem_after_mb, ...
                                   'packed',    info.packed));
                    catch
                    end
                end
            end

            % ---- graceful shutdown --------------------------------------
            try, obj.socket.close(); catch, end
            obj.socket = [];
            stats = obj.lc.get_stats();
            logger('info', 'server.stop', '', ...
                struct('total_requests', stats.total_requests, ...
                       'errors',          stats.error_count, ...
                       'uptime_s',        round(stats.uptime_s)));
            obj.running = false;
        end

        function stop(obj)
            %STOP  Signal the main loop to exit and close the listener.
            obj.running = false;
            try
                if ~isempty(obj.socket)
                    obj.socket.close();
                end
            catch
            end
        end

        function handle_shutdown(obj)
            %HANDLE_SHUTDOWN  Called by the dispatcher on SHUTDOWN_REQUEST.
            %   Signals the main loop to stop accepting new connections.
            %   In-flight requests finish naturally (single-threaded server).
            obj.running = false;
        end
    end

    methods (Access = private)
        function handle_client(obj, client)
            %HANDLE_CLIENT  Read one framed request, dispatch, send response.
            client.setSoTimeout(int32(120000));  % 2-minute read timeout
            dis = java.io.DataInputStream(client.getInputStream());
            dos = java.io.DataOutputStream(client.getOutputStream());

            % ---- read framed request ------------------------------------
            json_str = read_framed(dis, obj.cfg.max_request_bytes);

            if isempty(json_str)
                resp_env = obj.error_envelope('', 'ERR_INVALID', ...
                    'bad_frame', 'Empty or oversized request frame');
                send_framed(dos, json_codec('encode_struct', resp_env));
                return;
            end

            % ---- decode JSON envelope -----------------------------------
            env = json_codec('decode_request', json_str);
            if isfield(env, '__decode_error')
                resp_env = obj.error_envelope('', 'ERR_INVALID', ...
                    'json_decode', env.__decode_error);
                send_framed(dos, json_codec('encode_struct', resp_env));
                return;
            end

            % ---- build context & dispatch -------------------------------
            ctx = struct();
            ctx.cfg      = obj.cfg;
            ctx.reg      = obj.reg;
            ctx.lc       = obj.lc;
            ctx.shutdown = @() obj.handle_shutdown();

            resp_env = dispatcher(env, ctx);

            % ---- send framed response -----------------------------------
            resp_json = json_codec('encode_struct', resp_env);
            send_framed(dos, resp_json);
        end

        function env = error_envelope(obj, req_id, status, err_code, err_msg)
            %ERROR_ENVELOPE  Build a minimal AlgorithmResponse error envelope.
            resp = struct();
            resp.status        = status;
            resp.error_code    = err_code;
            resp.error_message = err_msg;
            resp.results       = struct();
            resp.artifacts     = struct();
            resp.request_id    = req_id;

            env = struct();
            env.request_id   = req_id;
            env.timestamp_ms = int64(posix_now_ms());
            env.message_type = 'ALGORITHM_RESPONSE';
            env.protocol_ver = obj.cfg.protocol_ver;
            env.payload      = resp;
        end
    end
end

% ============================================================
% Local helper functions (accessible from class methods)
% ============================================================

function json_str = read_framed(dis, max_bytes)
%READ_FRAMED  Read one 4-byte-big-endian-length-prefixed JSON message.
%   Returns '' on error (empty / oversized / stream closed). The caller
%   checks for empty and sends an error envelope.
    json_str = '';
    try
        len = dis.readInt();   % 4-byte big-endian int32
    catch
        return;   % stream closed or truncated
    end

    if len <= 0, return; end

    if len > max_bytes
        % Drain the payload to keep the stream framed, then signal error.
        try, dis.skipBytes(int32(len)); catch, end
        return;
    end

    data = read_n_bytes(dis, len);
    if isempty(data), return; end
    json_str = native2unicode(data, 'UTF-8');
end

function data = read_n_bytes(dis, n)
%READ_N_BYTES  Read exactly n bytes from a DataInputStream as uint8.
%   Prefers Java 11+ InputStream.readNBytes(int) which returns a byte[]
%   (bulk read, efficient). Falls back to byte-by-byte dis.read() when
%   readNBytes is unavailable (older Java bundled with MATLAB < R2019a).
    data = zeros(1, n, 'uint8');
    pos = 1;
    use_bulk = true;

    % Probe readNBytes availability once with a zero-length request.
    try
        dis.readNBytes(int32(0));
    catch
        use_bulk = false;
    end

    while pos <= n
        if use_bulk
            try
                jb = dis.readNBytes(int32(min(n - pos + 1, 65536)));
                if isempty(jb)
                    break;   % EOF
                end
                chunk = uint8(jb);
                data(pos:pos + numel(chunk) - 1) = chunk;
                pos = pos + numel(chunk);
                continue;
            catch
                use_bulk = false;   % fall through to byte-by-byte
            end
        end
        % Byte-by-byte fallback
        b = dis.read();
        if b < 0, break; end   % EOF
        data(pos) = uint8(b);
        pos = pos + 1;
    end

    data = data(1:pos - 1);
end

function send_framed(dos, json_str)
%SEND_FRAMED  Write a 4-byte big-endian length prefix + UTF-8 JSON payload.
    bytes = unicode2native(json_str, 'UTF-8');
    n = int32(numel(bytes));
    try
        dos.writeInt(n);
        if n > 0
            dos.write(int8(bytes), int32(0), n);
        end
        dos.flush();
    catch
        % socket closed or write error - nothing the caller can do
    end
end

function ts = posix_now_ms()
%POSIX_NOW_MS  Current UTC time in milliseconds since the Unix epoch.
    ts = round(posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000);
end
