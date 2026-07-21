"""
test_auto_updater.py — 自动更新检查 (check_for_updates) 单元测试

被测模块: repair_app/utils/auto_updater.py

说明:
    源码以模块级函数实现 (check_for_updates / _compare_versions),
    不存在 AutoUpdater 类。测试按实际 API 编写, 所有网络请求均被 mock,
    不会发起真实网络连接。
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import urllib.error

import repair_app.utils.auto_updater as au
from repair_app.utils.auto_updater import _compare_versions, check_for_updates


class TestCompareVersions:
    """版本号比较逻辑 (_compare_versions)。"""

    def test_equal_versions(self):
        assert _compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_major(self):
        assert _compare_versions("2.0.0", "1.0.0") == 1

    def test_lesser_major(self):
        assert _compare_versions("1.0.0", "2.0.0") == -1

    def test_greater_minor(self):
        assert _compare_versions("1.2.0", "1.1.0") == 1

    def test_greater_patch(self):
        assert _compare_versions("1.0.1", "1.0.0") == 1

    def test_different_length_padding(self):
        # "1.0" 视为 "1.0.0"
        assert _compare_versions("1.0", "1.0.0") == 0
        assert _compare_versions("1.0.1", "1.0") == 1

    def test_invalid_version_returns_zero(self):
        # 非数字片段 => ValueError 被捕获 => 返回 0
        assert _compare_versions("x.y", "1.0.0") == 0
        assert _compare_versions("1.0.0", "a.b.c") == 0

    def test_empty_strings(self):
        assert _compare_versions("", "") == 0


class TestCheckForUpdatesNoUrl:
    """无更新源 URL 时应安全跳过。"""

    def test_no_url_returns_false_none(self, monkeypatch):
        monkeypatch.setattr(au, "_UPDATE_URL", "")
        available, version = check_for_updates("1.0.0")
        assert available is False
        assert version is None

    def test_empty_update_url_arg_falls_back_to_module(self, monkeypatch):
        # update_url="" (falsy) => 回退到 _UPDATE_URL
        monkeypatch.setattr(au, "_UPDATE_URL", "")
        available, version = check_for_updates("1.0.0", update_url="")
        assert available is False
        assert version is None


def _mock_response(status: int, payload=None) -> MagicMock:
    """构造一个可作上下文管理器使用的 urlopen 返回 mock。"""
    m = MagicMock()
    m.status = status
    m.__enter__.return_value = m
    body = json.dumps(payload).encode() if payload is not None else b"{}"
    m.read.return_value = body
    return m


class TestCheckForUpdatesWithMock:
    """mock 网络请求, 验证版本解析与比较。"""

    def test_newer_version_available(self):
        resp = _mock_response(200, {"tag_name": "v1.2.0"})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is True
        assert version == "1.2.0"

    def test_older_version_not_available(self):
        resp = _mock_response(200, {"tag_name": "v0.5.0"})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        # 旧版本仍返回版本号字符串 (而非 None)
        assert version == "0.5.0"

    def test_same_version_not_available(self):
        resp = _mock_response(200, {"tag_name": "1.0.0"})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version == "1.0.0"

    def test_tag_name_without_v_prefix(self):
        resp = _mock_response(200, {"tag_name": "2.0.0"})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is True
        assert version == "2.0.0"

    def test_empty_tag_name(self):
        resp = _mock_response(200, {"tag_name": ""})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version is None

    def test_missing_tag_name_key(self):
        resp = _mock_response(200, {"name": "some release"})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version is None

    def test_non_200_status(self):
        resp = _mock_response(404, {})
        with patch("urllib.request.urlopen", return_value=resp):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version is None

    def test_url_error_returns_false_none(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network down")):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version is None

    def test_generic_exception_returns_false_none(self):
        with patch("urllib.request.urlopen", side_effect=ValueError("bad json")):
            available, version = check_for_updates("1.0.0", update_url="http://example.test")
        assert available is False
        assert version is None

    def test_no_real_network_request(self):
        """确保 urlopen 被完全 mock，且以正确 URL 调用。"""
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(200, {"tag_name": "v9.9.9"})
            check_for_updates("1.0.0", update_url="http://example.test")
            # 验证：urlopen 被调用（不只是 called）
            assert mock_open.called, "urlopen 应被调用"
            # 验证：以正确的 URL 参数调用
            call_args = mock_open.call_args
            assert call_args is not None, "应记录调用参数"
            url_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            # url_arg 可能是 Request 对象或字符串
            url_str = getattr(url_arg, "full_url", None) or str(url_arg)
            assert "example.test" in url_str, \
                f"应以正确 URL 调用，实际: {url_str}"
