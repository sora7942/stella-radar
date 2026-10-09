"""테스트용 가짜 Claude API (네트워크 없음). claude_events.Client(post=FakePost(...))로 주입한다.
test_claude_events.py·test_auto_events.py·test_main.py가 함께 쓴다."""
import json

import requests

from conftest import make_response

KEY = "sk-test-FAKE-not-a-real-key-0123456789"  # 모양이 sk-ant-가 아니라 비밀 스캔에 걸리지 않는다
SECRET_BODY = "SECRET-NOTICE-BODY-SENTINEL"  # 응답 원문이 로그·예외에 새지 않는지 확인하는 표지
MODEL = "claude-haiku-4-5-20251001"


def reply(payload, *, stop_reason="end_turn", model=MODEL):
    """모델이 payload(dict·list면 JSON으로, 문자열이면 그대로)를 말한 응답 (Messages API 모양)."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    body = {"id": "msg_x", "type": "message", "role": "assistant", "model": model, "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    return make_response(200, json.dumps(body))


def events_reply(*events, **kw):
    return reply({"events": list(events)}, **kw)


def error_reply(status, etype="api_error", message=SECRET_BODY):
    return make_response(status, json.dumps({"type": "error", "error": {"type": etype, "message": message}}))


def ev(kind="popup", title="STELLA MODE:ON 팝업스토어", start="2026-10-23", **extra):
    return {"kind": kind, "title": title, "start": start, "who": ["all"], **extra}


class FakePost:
    """http.post_json 대용. 호출마다 outcomes를 차례로 돌려준다(하나 남으면 그것을 계속). Response는 상태에 따라 HTTPError로, 예외는 그대로 던진다.
    calls에 (url, payload, headers, timeout)를 기록한다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple] = []

    def __call__(self, url, payload=None, *, headers=None, timeout=None, session=None):
        self.calls.append((url, payload, headers, timeout))
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        if out.status_code >= 400:
            raise requests.HTTPError(f"{out.status_code} Client Error for url: {url}", response=out)
        return out
