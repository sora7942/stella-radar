"""모든 외부 요청의 단일 통로: timeout=10과 User-Agent를 여기서 강제한다 (CLAUDE.md)."""
import requests

from . import config


def get(url: str, *, session: requests.Session | None = None, headers: dict | None = None) -> requests.Response:
    """GET. 4xx/5xx면 requests.HTTPError(.response 포함)를 던진다. 재시도는 호출하는 쪽 책임."""
    merged = {"User-Agent": config.USER_AGENT, **(headers or {})}
    resp = (session or requests).get(url, headers=merged, timeout=config.TIMEOUT)
    resp.raise_for_status()
    return resp


def post_json(url: str, payload: dict | None = None, *, session: requests.Session | None = None, headers: dict | None = None,
              timeout: float | None = None) -> requests.Response:
    """POST(JSON). get과 같이 timeout=10과 User-Agent를 강제한다. 4xx/5xx면 requests.HTTPError(.response 포함).
    payload가 None이면 본문 없이 보낸다 (예: GitHub 실행 취소). headers는 User-Agent 위에 덧붙는다.
    timeout은 기본 config.TIMEOUT(10)이고, 모델 응답을 기다리는 Claude 호출만 config.CLAUDE_TIMEOUT(30)을 명시한다 (CLAUDE.md Rules의 유일한 예외).
    주의: requests 예외의 메시지에는 URL이 들어간다. 웹훅 URL을 다루는 호출자는 예외 메시지를 로그에 남기면 안 된다."""
    merged = {"User-Agent": config.USER_AGENT, **(headers or {})}
    resp = (session or requests).post(url, json=payload, headers=merged, timeout=config.TIMEOUT if timeout is None else timeout)
    resp.raise_for_status()
    return resp
