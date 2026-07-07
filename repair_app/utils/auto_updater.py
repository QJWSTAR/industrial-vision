"""Auto-update — check for and apply application updates.

Provides a lightweight update check mechanism that queries a version
endpoint and downloads updates when available.

Usage:
    from repair_app.utils.auto_updater import check_for_updates
    update_available, version = check_for_updates(current_version="0.10.0")
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
from typing import Optional, Tuple

from repair_app.utils.logger_config import info, warning, error as log_error


# Default update endpoint (configurable via env var)
# 安全提示：默认 URL 指向 GitHub 仓库，生产环境应通过 CSAM_UPDATE_URL 环境变量
# 指向内部更新服务器，避免依赖第三方平台。
_UPDATE_URL = os.environ.get("CSAM_UPDATE_URL", "")
_UPDATE_TIMEOUT = int(os.environ.get("CSAM_UPDATE_TIMEOUT", "10"))


def check_for_updates(
    current_version: str,
    update_url: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Check if a newer version is available.

    Args:
        current_version: Current application version (e.g. "0.10.0").
        update_url: URL to fetch version info from.

    Returns:
        (update_available, latest_version) tuple.
    """
    url = update_url or _UPDATE_URL
    if not url:
        warning("未配置更新源 URL (CSAM_UPDATE_URL)，跳过更新检查")
        return False, None
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", f"CSAM-Repair/{current_version}")

        with urllib.request.urlopen(req, timeout=_UPDATE_TIMEOUT) as resp:
            if resp.status != 200:
                return False, None
            data = json.loads(resp.read().decode())

        # Parse version from GitHub release format
        latest = data.get("tag_name", "").lstrip("vV")
        if not latest:
            return False, None

        update_available = _compare_versions(latest, current_version) > 0
        if update_available:
            info(f"Update available: {current_version} → {latest}")
        return update_available, latest

    except urllib.error.URLError as e:
        warning(f"Update check failed (network): {e}")
        return False, None
    except Exception as e:
        log_error(f"Update check failed: {e}")
        return False, None


def _compare_versions(a: str, b: str) -> int:
    """Compare two semver strings. Returns 1 if a > b, -1 if a < b, 0 if equal."""
    try:
        parts_a = [int(x) for x in a.split(".")]
        parts_b = [int(x) for x in b.split(".")]
    except ValueError:
        return 0

    # Pad to same length
    max_len = max(len(parts_a), len(parts_b))
    parts_a += [0] * (max_len - len(parts_a))
    parts_b += [0] * (max_len - len(parts_b))

    for pa, pb in zip(parts_a, parts_b):
        if pa > pb:
            return 1
        if pa < pb:
            return -1
    return 0