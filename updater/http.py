"""모든 외부 요청의 단일 통로: timeout=10과 User-Agent를 여기서 강제한다 (CLAUDE.md)."""
import requests

from . import config


def get(url: str, *, session: requests.Session | None = None, headers: dict | None = None) -> requests.Response:
    """GET. 4xx/5xx면 requests.HTTPError(.response 포함)를 던진다. 재시도는 호출하는 쪽 책임."""
    merged = {"User-Agent": config.USER_AGENT, **(headers or {})}
    resp = (session or requests).get(url, headers=merged, timeout=config.TIMEOUT)
    resp.raise_for_status()
    return resp
