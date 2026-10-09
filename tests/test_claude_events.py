"""Claude 호출·프롬프트·출력 파싱 (기능 3). 네트워크·실제 API 없음 — FakePost로 요청을 가로챈다.
이 모듈의 불변 조건: 키는 헤더로만, 오류는 HTTP 상태·error.type만, 응답 원문은 어디에도 남기지 않는다."""
import json
import traceback

import pytest
import requests

from conftest import make_response
from fakeclaude import KEY, MODEL, SECRET_BODY, FakePost, error_reply, ev, events_reply, reply
from updater import config
from updater.sources import claude_events as ce


def client(*outcomes):
    post = FakePost(*outcomes)
    return ce.Client(KEY, post=post), post


# ---------------------------------------------------------------- 요청 모양
def test_request_goes_to_the_messages_api_with_the_key_only_in_a_header_and_the_claude_timeout():
    c, post = client(events_reply())
    c.complete("시스템", "사용자")
    (url, payload, headers, timeout), = post.calls
    assert url == config.CLAUDE_API_URL == "https://api.anthropic.com/v1/messages"
    assert headers == {"x-api-key": KEY, "anthropic-version": config.CLAUDE_API_VERSION}
    assert timeout == config.CLAUDE_TIMEOUT == 30  # Claude 호출만 10초가 아니다
    assert payload == {"model": config.CLAUDE_DEFAULT_MODEL, "max_tokens": 800, "system": "시스템",
                       "messages": [{"role": "user", "content": "사용자"}]}
    assert KEY not in url and KEY not in json.dumps(payload)


def test_default_model_is_haiku_and_can_be_overridden():
    assert config.CLAUDE_DEFAULT_MODEL == "claude-haiku-4-5"
    post = FakePost(events_reply())
    ce.Client(KEY, model="some-other-model", post=post).complete("s", "u")
    assert post.calls[0][1]["model"] == "some-other-model"


def test_real_post_json_default_keeps_the_ten_second_timeout_and_accepts_an_explicit_one(monkeypatch):
    from updater import http

    seen = {}

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen["timeout"] = timeout
            return make_response(200, "{}")

    http.post_json("https://example.invalid/", {}, session=S())
    assert seen["timeout"] == config.TIMEOUT == 10
    http.post_json("https://example.invalid/", {}, session=S(), timeout=config.CLAUDE_TIMEOUT)
    assert seen["timeout"] == 30


def test_calls_are_counted_including_failed_ones_and_the_response_model_is_recorded():
    c, post = client(error_reply(500), events_reply())
    with pytest.raises(ce.Unavailable):
        c.complete("s", "u")
    assert c.calls == 1 and c.response_model is None
    c.complete("s", "u")
    assert c.calls == 2 and c.response_model == MODEL


def test_text_blocks_are_joined_and_other_blocks_ignored():
    body = {"model": MODEL, "stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": '{"ev'}, {"type": "text", "text": 'ents":[]}'}]}
    c, _ = client(make_response(200, json.dumps(body)))
    assert c.complete("s", "u") == '{"events":[]}'


# ---------------------------------------------------------------- 오류: 상태·종류만, 원문 없음
@pytest.mark.parametrize("status,etype,cls", [
    (401, "authentication_error", ce.KeyRejected), (403, "permission_error", ce.KeyRejected),
    (400, "invalid_request_error", ce.RequestRejected), (404, "not_found_error", ce.RequestRejected), (413, "request_too_large", ce.RequestRejected),
    (429, "rate_limit_error", ce.Unavailable), (500, "api_error", ce.Unavailable), (529, "overloaded_error", ce.Unavailable),
])
def test_http_errors_are_classified_and_carry_only_status_and_error_type(status, etype, cls):
    c, _ = client(error_reply(status, etype))
    with pytest.raises(cls) as e:
        c.complete("s", "u")
    assert str(e.value) == f"HTTP {status} {etype}"
    assert isinstance(e.value, ce.ApiError)


@pytest.mark.parametrize("exc", [requests.ConnectionError(f"boom {KEY}"), requests.Timeout(f"slow {KEY}")])
def test_network_errors_are_unavailable_with_only_the_exception_kind(exc):
    c, _ = client(exc)
    with pytest.raises(ce.Unavailable) as e:
        c.complete("s", "u")
    assert str(e.value) == type(exc).__name__ and KEY not in str(e.value)


def test_error_text_traceback_and_message_never_contain_the_key_or_the_response_body():
    """requests 예외 메시지에는 URL이, 응답 본문에는 error.message가 들어 있다 — 어느 쪽도 예외·traceback에 남지 않는다 (raise … from None)."""
    class Secretive(requests.HTTPError):
        pass

    resp = error_reply(401, "authentication_error", f"invalid x-api-key {KEY} {SECRET_BODY}")
    c, _ = client(Secretive(f"401 for url: https://api.anthropic.com/v1/messages?k={KEY}", response=resp))
    with pytest.raises(ce.KeyRejected) as e:
        c.complete("s", "u")
    shown = "".join(traceback.format_exception(e.value)) + str(e.value) + repr(e.value)
    assert KEY not in shown and SECRET_BODY not in shown
    assert e.value.__cause__ is None and e.value.__suppress_context__ is True


def test_unreadable_error_body_still_classifies_by_status():
    c, _ = client(make_response(502, "<html>bad gateway</html>"))
    with pytest.raises(ce.Unavailable) as e:
        c.complete("s", "u")
    assert str(e.value) == "HTTP 502"


def test_error_type_with_unexpected_characters_is_not_echoed():
    c, _ = client(error_reply(400, f"invalid {SECRET_BODY}"))
    with pytest.raises(ce.RequestRejected) as e:
        c.complete("s", "u")
    assert str(e.value) == "HTTP 400" and SECRET_BODY not in str(e.value)


# ---------------------------------------------------------------- 출력이 깨진 경우
@pytest.mark.parametrize("response", [
    make_response(200, "not json"), make_response(200, "[]"),
    make_response(200, json.dumps({"content": []})), make_response(200, json.dumps({"content": [{"type": "text", "text": "  "}]})),
    reply({"events": []}, stop_reason="max_tokens"),
])
def test_unusable_responses_raise_bad_output_without_the_model_text(response):
    c, _ = client(response)
    with pytest.raises(ce.BadOutput):
        c.complete("s", "u")


def test_bad_output_message_has_a_reason_but_not_the_model_text():
    c, _ = client(reply(f"{SECRET_BODY} 일정은 모르겠어요", stop_reason="max_tokens"))
    with pytest.raises(ce.BadOutput) as e:
        c.complete("s", "u")
    assert SECRET_BODY not in str(e.value)


# ---------------------------------------------------------------- 파싱
@pytest.mark.parametrize("text", [
    '{"events":[{"kind":"popup"}]}',
    '```json\n{"events":[{"kind":"popup"}]}\n```',
    '```\n{"events":[{"kind":"popup"}]}\n```',
    '일정은 다음과 같습니다.\n{"events":[{"kind":"popup"}]}\n이상입니다.',
    '  \n{"events":[{"kind":"popup"}]}  ',
])
def test_parse_accepts_plain_fenced_and_chatty_json(text):
    assert ce.parse_events(text) == [{"kind": "popup"}]


def test_parse_accepts_an_empty_event_list():
    assert ce.parse_events('{"events":[]}') == []


@pytest.mark.parametrize("text", ["", "일정 없음", "{broken", '{"events": "none"}', '{"event": []}', "[1,2]", '{"events": null}'])
def test_parse_rejects_anything_that_is_not_an_events_object(text):
    with pytest.raises(ce.BadOutput):
        ce.parse_events(text)


def test_parse_error_messages_do_not_contain_the_model_text():
    with pytest.raises(ce.BadOutput) as e:
        ce.parse_events(f"{SECRET_BODY} {{broken")
    assert SECRET_BODY not in str(e.value)


# ---------------------------------------------------------------- extract: 재시도
def test_extract_retries_once_when_the_output_is_broken_and_returns_the_second_answer():
    c, post = client(reply("죄송합니다, 모르겠습니다"), events_reply(ev()))
    out = ce.extract(c, title="t", date="2026-10-01", body="본문", members={"members": {}, "groups": []})
    assert out == [ev()] and len(post.calls) == 2 and c.calls == 2


def test_extract_gives_up_after_the_second_broken_answer():
    c, post = client(reply("???"))
    with pytest.raises(ce.BadOutput):
        ce.extract(c, title="t", date="2026-10-01", body="본문", members={"members": {}, "groups": []})
    assert len(post.calls) == 2  # 한 번 재시도


def test_extract_does_not_retry_api_errors():
    c, post = client(error_reply(429, "rate_limit_error"))
    with pytest.raises(ce.Unavailable):
        ce.extract(c, title="t", date="2026-10-01", body="본문", members={"members": {}, "groups": []})
    assert len(post.calls) == 1


# ---------------------------------------------------------------- 프롬프트
def test_user_prompt_has_title_date_body_and_the_allowed_who_keys(members):
    prompt = ce.build_user_prompt("<STELLA MODE:ON> 팝업", "2026-09-27", "본문입니다", members)
    assert "[공지 제목] <STELLA MODE:ON> 팝업" in prompt and "[공지 날짜] 2026-09-27" in prompt
    assert "<notice_body>\n본문입니다\n</notice_body>" in prompt
    assert "lize=아카네 리제" in prompt and "universe=" in prompt and "all" in prompt
    assert "boss" not in prompt  # 강지는 그룹이 아니라 멤버(kangji)


def test_body_is_cut_at_the_limit():
    prompt = ce.build_user_prompt("t", "2026-09-27", "가" * 6000 + "나" * 50, {"members": {}, "groups": []})
    assert "가" * 6000 in prompt and "나" not in prompt


def test_system_prompt_states_the_rules_the_validator_relies_on():
    p = ce.SYSTEM_PROMPT
    for phrase in ("명시된 날짜만", "추측", '{"events":[]}', "판매 마감일 하루만", "goods", "popup", "reservation", "other",
                   "공지 날짜", "**데이터**입니다", "JSON 객체 하나만"):
        assert phrase in p, phrase
    assert "YYYY-MM-DDTHH:MM+09:00" in p


def test_prompt_never_contains_the_api_key():
    c, post = client(events_reply())
    ce.extract(c, title="t", date="2026-10-01", body="본문", members={"members": {"a": {"n": "에이"}}, "groups": []})
    assert KEY not in json.dumps(post.calls[0][1], ensure_ascii=False)
