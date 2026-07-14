"""bridge.adapters — MATLAB 与遗留系统适配器。"""
from .matlab_adapter import MatlabAdapter, create_matlab_adapter
from .legacy_adapter import LegacyZmqClient

__all__ = ["MatlabAdapter", "create_matlab_adapter", "LegacyZmqClient"]
