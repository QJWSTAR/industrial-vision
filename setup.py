"""Minimal setup.py for backward compatibility with pip < 21.3.

Modern builds use pyproject.toml (PEP 517/621).
This file exists solely to support older pip versions that require
a setup.py for editable installs (`pip install -e .`).
"""

from setuptools import setup

setup()