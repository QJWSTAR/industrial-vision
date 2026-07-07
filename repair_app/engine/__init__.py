"""Engine layer — concrete engine implementations.

Provides LocalEngine (Python prototype) and serves as the extension point
for future MATLAB ZMQ engine.
"""

from repair_app.engine.local_engine import LocalEngine

__all__ = ["LocalEngine"]