import pytest
import requests

from conftest import NetworkBlocked, make_response
from updater import config, http


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_get_forces_timeout_and_user_agent():
    s = FakeSession(make_response(200, b"ok"))
    http.get("https://example.invalid/x", session=s)
    (url, kw), = s.calls
    assert kw["timeout"] == config.TIMEOUT == 10
    assert kw["headers"]["User-Agent"] == config.USER_AGENT
    assert "Mozilla" in config.USER_AGENT  # 브라우저 형태


def test_extra_headers_are_merged_with_user_agent_kept():
    s = FakeSession(make_response(200))
    http.get("https://example.invalid/x", session=s, headers={"Accept": "application/json"})
    assert s.calls[0][1]["headers"] == {"User-Agent": config.USER_AGENT, "Accept": "application/json"}


@pytest.mark.parametrize("status", [404, 500])
def test_http_errors_raise_with_response(status):
    with pytest.raises(requests.HTTPError) as ei:
        http.get("https://example.invalid/x", session=FakeSession(make_response(status)))
    assert ei.value.response.status_code == status


def test_real_network_is_blocked_in_tests():
    # conftest의 차단이 실제로 걸려 있는지: 세션 없이 호출하면 소켓 단계에서 막힌다
    with pytest.raises((NetworkBlocked, requests.ConnectionError)):
        http.get("https://example.invalid/")


class FakePostSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_post_json_forces_timeout_and_user_agent_and_sends_json():
    s = FakePostSession(make_response(204))
    http.post_json("https://example.invalid/hook", {"a": "한글"}, session=s)
    (url, kw), = s.calls
    assert url == "https://example.invalid/hook" and kw["json"] == {"a": "한글"}
    assert kw["timeout"] == config.TIMEOUT == 10 and kw["headers"] == {"User-Agent": config.USER_AGENT}


def test_post_json_raises_on_error_status_with_response():
    with pytest.raises(requests.HTTPError) as ei:
        http.post_json("https://example.invalid/hook", {}, session=FakePostSession(make_response(429, b"{}")))
    assert ei.value.response.status_code == 429


def test_post_json_real_network_is_blocked_in_tests():
    with pytest.raises((NetworkBlocked, requests.ConnectionError)):
        http.post_json("https://example.invalid/hook", {})
