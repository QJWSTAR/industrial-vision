"""[DEPRECATED] Engine factory — selects the best available algorithm engine.

.. deprecated::
    This factory builds the DEPRECATED MatlabEngine (TCP/JSON/Protocol v3.0/
    port 5570). The finalized production communication path does NOT use this
    engine subtree at all:

        GUI -> CoordinationService -> MatlabService / LegacyZmqClient
             -> Bridge -> ZeroMQ (port 5555) -> Protocol Buffers (v2.1)
             -> matlab_bridge_server.m -> MATLAB R2025b

    The GUI never calls ``create_engine()``; it reaches MATLAB through
    ``CoordinationService.create_zmq_client()`` -> ``LegacyZmqClient`` ->
    ``BridgeClient``. This factory is retained only for backward compatibility,
    the benchmark tool, and the mock-server test suite. Do NOT wire it into
    production code. See docs/COMMUNICATION.md.

Original description (for historical reference):
    Tries MatlabEngine first (production path), falls back to LocalEngine
    (Python prototype) if MATLAB Server is unavailable.
"""
from __future__ import annotations

import logging
import os
import warnings
from typing import Optional

from repair_app.domain.interfaces import IEngine
from repair_app.engine.local_engine import LocalEngine

logger = logging.getLogger("csam.engine.factory")


def _create_matlab_engine() -> Optional[IEngine]:
    """Try to create and validate a MatlabEngine. Returns None if unavailable."""
    if os.environ.get("CSAM_ENGINE_DISABLE_MATLAB", "0") == "1":
        logger.info("MatlabEngine disabled via CSAM_ENGINE_DISABLE_MATLAB=1")
        return None
    try:
        from repair_app.engine.matlab_engine import MatlabEngine
        engine = MatlabEngine()
        if engine.is_available:
            logger.info("MatlabEngine available and healthy — using as production engine")
            return engine
        logger.info("MatlabEngine not reachable — falling back to LocalEngine")
        engine.close()
    except Exception as e:
        logger.warning("MatlabEngine creation failed: %s — falling back to LocalEngine", e)
    return None


def create_engine(preference: str = "auto") -> IEngine:
    """Create the best available engine.

    .. deprecated::
        Emits DeprecationWarning because the MatlabEngine path (TCP/JSON/
        v3.0/5570) is no longer the production communication path. The GUI
        uses the Bridge (ZeroMQ/Protobuf/5555) directly via
        CoordinationService. See docs/COMMUNICATION.md.

    Args:
        preference: "matlab" (require MATLAB, raise if unavailable),
                    "python" (force LocalEngine),
                    "auto" (try MATLAB, fall back to Python).
    """
    warnings.warn(
        "engine.factory.create_engine() is DEPRECATED: it builds the "
        "TCP/JSON/v3.0/5570 MatlabEngine, which is no longer the production "
        "path. Production uses ZeroMQ/Protobuf/5555 via repair_app.bridge. "
        "See docs/COMMUNICATION.md.",
        DeprecationWarning,
        stacklevel=2,
    )
    if preference == "python":
        logger.info("Forcing LocalEngine (preference=python)")
        return LocalEngine()

    matlab = _create_matlab_engine()
    if matlab is not None:
        return matlab

    if preference == "matlab":
        raise RuntimeError("MATLAB engine required but unavailable")

    logger.info("Using LocalEngine (Python prototype) as fallback")
    return LocalEngine()
