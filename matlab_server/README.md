# [DEPRECATED] CSAM MATLAB Server (TCP / JSON / Protocol v3.0 / port 5570)

> **⚠️ DEPRECATED — DO NOT USE IN PRODUCTION**
>
> This MATLAB server implements the **TCP + JSON + Protocol v3.0 + port 5570**
> communication stack, which has been **SUPERSEDED** by the finalized production
> communication architecture.
>
> **The ONLY production communication path is:**
>
> ```
> GUI -> CoordinationService -> MatlabService / LegacyZmqClient
>     -> Bridge -> ZeroMQ (port 5555) -> Protocol Buffers (v2.1)
>     -> matlab_bridge_server.m -> MATLAB R2025b
> ```
>
> The production MATLAB server entry point is `../matlab_bridge_server.m`
> (ZeroMQ REQ/REP on port 5555, Protobuf v2.1). This `matlab_server/` directory
> is retained ONLY for backward compatibility and historical reference. It must
> NOT be started for production use. See `../docs/COMMUNICATION.md` for the
> deprecation rationale and timeline.

---

# CSAM MATLAB Server (historical reference)

Production-grade MATLAB algorithm server for the CSAM Repair industrial vision
project. Hosts 19 algorithm functions (7 path-planning + 12 morphology) and
serves them over a JSON-over-TCP wire format mirroring Protocol Buffers v3.0.

## Quick Start

```matlab
% From the MATLAB command window:
cd('D:\work\demo\industrial-vision\matlab_server')
startup
```

The server blocks the MATLAB command window until a `SHUTDOWN_REQUEST` is
received or `stop()` is called on the server instance.

## Transport & Wire Format

- **Transport**: `java.net.ServerSocket` (no ZMQ dependency; always available
  via the JVM bundled with MATLAB).
- **Framing**: 4-byte big-endian uint32 length prefix + UTF-8 JSON payload.
- **Protocol**: JSON envelope mirroring `algorithm_protocol_v3.proto`:
  `{request_id, timestamp_ms, message_type, protocol_ver, payload}`.
- **Binary data**: base64-encoded within JSON `Tensor` objects
  (`{dtype, shape, data, units}`). Row-major (protobuf) to column-major
  (MATLAB) conversion is handled by `json_codec.m`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CSAM_MATLAB_BIND` | `tcp://*:5570` | Bind address (`tcp://host:port`) |
| `CSAM_MATLAB_LOG_DIR` | `<repo>/logs` | Log directory (JSONL files) |
| `CSAM_MATLAB_HEARTBEAT_MS` | `1000` | Heartbeat interval (ms) |
| `CSAM_MATLAB_MAX_REQ_BYTES` | `67108864` | Max request size (64 MB) |
| `CSAM_MATLAB_CLEANUP_INTERVAL` | `50` | Requests between cleanup cycles |
| `CSAM_MATLAB_MEM_THRESHOLD_MB` | `4096` | Memory threshold for `pack` |
| `CSAM_MATLAB_LOG_LEVEL` | `info` | Log level: debug / info / warn / error |

## Dependencies

- **MATLAB R2018b+** (uses `jsonencode`, `jsondecode`, `containers.Map`,
  `datetime`/`posixtime`).
- **Java 11+** (bundled with MATLAB R2019a+) for `InputStream.readNBytes`.
  Falls back to byte-by-byte reads on older Java.
- **Map Toolbox** — required by: `layer_slice`, `model_process`,
  `generate_path`, `spot_interp`, `classify_removed_triangles`,
  `improve_short_edges`, `profile_predict`.
- **Curve Fitting Toolbox** — required by: `particle_fitting`.

Toolbox availability is probed at runtime via `license('test', ...)`. Missing
toolboxes degrade the server health state to `DEGRADED` and cause dependent
algorithm calls to return `ERR_DEPS`.

## Message Types

| Type | Direction | Response | Description |
|------|-----------|----------|-------------|
| `ALGORITHM_REQUEST` | C->S | `ALGORITHM_RESPONSE` | Invoke an algorithm |
| `HEARTBEAT` | C->S | `PONG` | Liveness probe |
| `HEALTH_CHECK` | C->S | `HEALTH_STATUS` | Server health (memory, toolboxes, error rate) |
| `LIST_ALGORITHMS` | C->S | `LIST_ALGORITHMS_RESPONSE` | List registered algorithms |
| `VERSION_NEGOTIATE` | C->S | `VERSION_RESULT` | Protocol version negotiation |
| `CANCELLATION` | C->S | `CANCELLATION` (ack) | Cancel request (no-op; single-threaded) |
| `SHUTDOWN_REQUEST` | C->S | `SHUTDOWN_ACK` | Graceful server shutdown |

## Files

| File | Purpose |
|------|---------|
| `startup.m` | Entry point: configures path and starts the server |
| `config.m` | Configuration struct from environment variables |
| `server.m` | Main server classdef (TCP loop, framing, run/stop) |
| `dispatcher.m` | Message-type routing and crash-guarded algorithm dispatch |
| `registry.m` | Algorithm registry (`containers.Map`) |
| `register_algorithms.m` | Registers all 19 algorithm wrappers |
| `lifecycle.m` | Request counters, rolling error window, crash guard |
| `health.m` | Health status (toolboxes, memory, error rate, uptime) |
| `heartbeat.m` | Pong response builder |
| `resource_cleanup.m` | Periodic memory reclamation (Java GC + `pack`) |
| `json_codec.m` | JSON / Tensor / Value codec with base64 + row/col-major |
| `logger.m` | Structured JSONL logger (stdout + daily file) |

## Safety Guarantees

1. **Never crashes**: All algorithm calls are wrapped in `try/catch` via
   `lifecycle.crash_guard()`. The dispatcher has a top-level try/catch. The
   server loop wraps all I/O in try/catch. A single bad request cannot take
   the server down.
2. **No `clear all`**: The server never calls `clear all` or `clear` without
   arguments — that would destroy the running server's state.
3. **Single-threaded cleanup**: `resource_cleanup` runs synchronously between
   requests every `CSAM_MATLAB_CLEANUP_INTERVAL` requests. No background
   threads or timers (MATLAB is single-threaded).
4. **Structured logging**: JSONL to stdout and `<log_dir>/matlab_server_<date>.log`.
   Logging failures are silently swallowed and never crash the server.

## Example Request (Python)

```python
import socket, json, struct

env = {
    "request_id": "req-001",
    "timestamp_ms": 1719900000000,
    "message_type": "HEALTH_CHECK",
    "protocol_ver": "3.0",
    "payload": {"client_version": "demo-1.0"},
}
payload = json.dumps(env).encode("utf-8")

sock = socket.create_connection(("127.0.0.1", 5570))
sock.sendall(struct.pack(">I", len(payload)) + payload)
hdr = sock.recv(4)
resp_len = struct.unpack(">I", hdr)[0]
resp = json.loads(sock.recv(resp_len))
print(resp)
```
