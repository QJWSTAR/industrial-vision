"""[DEPRECATED] Lifecycle supervisor for MatlabEngine — industrial stability features.

.. deprecated::
    This supervisor manages the DEPRECATED MatlabEngine (TCP/JSON/Protocol
    v3.0/port 5570). The finalized production communication path uses ZeroMQ
    + Protocol Buffers (v2.1) on port 5555 via ``repair_app.bridge``, whose
    lifecycle/heartbeat is handled by ``bridge.communication.heartbeat``
    (HeartbeatMonitor) and ``bridge.communication.zmq_client`` (BridgeClient
    reconnect). This module is retained only for backward compatibility and
    the mock-server test suite. Do NOT use it in production code.
    See docs/COMMUNICATION.md.

Original description (for historical reference):
    Provides periodic heartbeat, automatic reconnection with exponential
    backoff, crash detection, circuit breaker, health monitoring, and
    request cancellation tracking for MatlabEngine.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

logger = logging.getLogger("csam.engine.lifecycle")


class CircuitState(IntEnum):
    CLOSED = 0       # normal operation
    OPEN = 1         # failing, reject requests
    HALF_OPEN = 2    # probing recovery


class EngineState(IntEnum):
    STOPPED = 0
    STARTING = 1
    READY = 2
    BUSY = 3
    DEGRADED = 4
    RECONNECTING = 5
    DEAD = 6


@dataclass
class LifecycleConfig:
    heartbeat_interval_ms: int = 2000
    heartbeat_timeout_ms: int = 3000
    miss_threshold: int = 3           # consecutive misses → RECONNECTING
    reconnect_initial_ms: int = 1000
    reconnect_max_ms: int = 30000
    reconnect_max_attempts: int = 10
    circuit_failure_threshold: int = 5
    circuit_reset_ms: int = 30000
    memory_restart_threshold_mb: float = 2048.0


class LifecycleSupervisor:
    """Monitors MatlabEngine health and manages reconnection.

    Usage:
        engine = MatlabEngine(...)
        sup = LifecycleSupervisor(engine, config)
        sup.start()
        ...
        sup.stop()
    """

    def __init__(self, engine, config: Optional[LifecycleConfig] = None) -> None:
        self._engine = engine
        self._cfg = config or LifecycleConfig.from_env()
        self._state = EngineState.STOPPED
        self._circuit = CircuitState.CLOSED
        self._miss_count = 0
        self._failure_count = 0
        self._reconnect_attempts = 0
        self._last_heartbeat_ts: Optional[float] = None
        self._last_success_ts: Optional[float] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_state_change: Optional[Callable[[EngineState], None]] = None
        self._on_degraded: Optional[Callable[[str], None]] = None
        self._on_recovered: Optional[Callable[[], None]] = None

    # ---- Configuration ----

    @staticmethod
    def _from_env() -> "LifecycleConfig":
        import os
        def _env(name: str, default: int) -> int:
            return int(os.environ.get(name, default))
        return LifecycleConfig(
            heartbeat_interval_ms=_env("CSAM_HEARTBEAT_INTERVAL_MS", 2000),
            heartbeat_timeout_ms=_env("CSAM_HEARTBEAT_TIMEOUT_MS", 3000),
            miss_threshold=_env("CSAM_HEARTBEAT_MISS_THRESHOLD", 3),
            reconnect_max_attempts=_env("CSAM_RECONNECT_MAX_ATTEMPTS", 10),
        )

    # ---- Callbacks ----

    def on_state_change(self, cb: Callable[[EngineState], None]) -> None:
        self._on_state_change = cb

    def on_degraded(self, cb: Callable[[str], None]) -> None:
        self._on_degraded = cb

    def on_recovered(self, cb: Callable[[], None]) -> None:
        self._on_recovered = cb

    # ---- State ----

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit

    @property
    def is_healthy(self) -> bool:
        return self._state in (EngineState.READY, EngineState.BUSY)

    def _set_state(self, new_state: EngineState) -> None:
        old = self._state
        self._state = new_state
        if old != new_state and self._on_state_change:
            try:
                self._on_state_change(new_state)
            except Exception:
                logger.exception("state change callback failed")

    # ---- Lifecycle ----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._set_state(EngineState.STARTING)
        self._thread = threading.Thread(
            target=self._run, name="MatlabEngineSupervisor", daemon=True
        )
        self._thread.start()
        logger.info("lifecycle supervisor started")

    def stop(self, timeout_ms: int = 3000) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_ms / 1000.0)
            self._thread = None
        self._set_state(EngineState.STOPPED)
        logger.info("lifecycle supervisor stopped")

    # ---- Main loop ----

    def _run(self) -> None:
        # Initial health probe
        if self._probe_health():
            self._set_state(EngineState.READY)
            self._last_success_ts = time.time()
        else:
            self._set_state(EngineState.DEGRADED)

        interval = self._cfg.heartbeat_interval_ms / 1000.0
        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            self._tick()

    def _tick(self) -> None:
        if self._state == EngineState.DEAD:
            return
        if self._state == EngineState.RECONNECTING:
            self._attempt_reconnect()
            return

        ok = self._probe_health()
        if ok:
            self._miss_count = 0
            self._last_heartbeat_ts = time.time()
            self._last_success_ts = time.time()
            if self._state == EngineState.DEGRADED:
                self._set_state(EngineState.READY)
                self._reconnect_attempts = 0
                if self._on_recovered:
                    try:
                        self._on_recovered()
                    except Exception:
                        logger.exception("recovered callback failed")
        else:
            self._miss_count += 1
            logger.warning("heartbeat miss %d/%d", self._miss_count, self._cfg.miss_threshold)
            if self._miss_count >= self._cfg.miss_threshold:
                logger.error("heartbeat miss threshold reached — entering RECONNECTING")
                self._set_state(EngineState.RECONNECTING)
                self._reconnect_attempts = 0

    def _probe_health(self) -> bool:
        try:
            return bool(self._engine.check_health())
        except Exception as e:
            logger.debug("health probe failed: %s", e)
            return False

    def _attempt_reconnect(self) -> None:
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._cfg.reconnect_max_attempts:
            logger.error("reconnect attempts exhausted — engine DEAD")
            self._set_state(EngineState.DEAD)
            if self._on_degraded:
                try:
                    self._on_degraded("MATLAB engine unreachable after max reconnect attempts")
                except Exception:
                    logger.exception("degraded callback failed")
            return

        backoff = min(
            self._cfg.reconnect_initial_ms * (2 ** (self._reconnect_attempts - 1)),
            self._cfg.reconnect_max_ms,
        )
        logger.info(
            "reconnect attempt %d/%d (backoff %.0fms)",
            self._reconnect_attempts, self._cfg.reconnect_max_attempts, backoff,
        )
        self._stop_event.wait(backoff / 1000.0)
        if self._stop_event.is_set():
            return

        # Try to reconnect
        try:
            self._engine._channel.disconnect()
            self._engine._channel.connect()
            if self._probe_health():
                logger.info("reconnect successful — engine READY")
                self._miss_count = 0
                self._reconnect_attempts = 0
                self._set_state(EngineState.READY)
                if self._on_recovered:
                    try:
                        self._on_recovered()
                    except Exception:
                        logger.exception("recovered callback failed")
        except Exception as e:
            logger.warning("reconnect attempt failed: %s", e)

    # ---- Circuit breaker ----

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._circuit == CircuitState.HALF_OPEN:
                self._circuit = CircuitState.CLOSED
                logger.info("circuit breaker CLOSED (recovered)")

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._cfg.circuit_failure_threshold:
                if self._circuit != CircuitState.OPEN:
                    self._circuit = CircuitState.OPEN
                    logger.error(
                        "circuit breaker OPEN after %d failures", self._failure_count
                    )

    @property
    def allow_request(self) -> bool:
        """Whether new requests should be allowed (circuit breaker check)."""
        if self._circuit == CircuitState.OPEN:
            # Check if reset timeout has elapsed → half-open
            if self._last_success_ts and (
                time.time() - self._last_success_ts > self._cfg.circuit_reset_ms / 1000.0
            ):
                self._circuit = CircuitState.HALF_OPEN
                logger.info("circuit breaker HALF_OPEN (probing)")
                return True
            return False
        return True


# Attach from_env to LifecycleConfig for convenience
LifecycleConfig.from_env = staticmethod(lambda: LifecycleSupervisor._from_env())  # type: ignore[attr-defined]
