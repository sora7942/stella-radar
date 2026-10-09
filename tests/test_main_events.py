"""공지 일정 추출이 main.py 흐름에 어떻게 붙는가 (기능 3-1 ②). test_main.py의 가짜 네트워크를 쓰고 상세 페이지·Claude는 가짜로 대신한다. 네트워크·실제 API 없음.
핵심: ① 키가 없으면 그 단계만 건너뛰고 이전 일정은 그대로 다시 쓴다(배포가 빈 시드로 덮지 않게) ② 키는 헤더로만, 로그·주석·파일에 없다
③ API 오류가 나도 실행은 성공하고 처리 기록은 소진되지 않는다 ④ 다른 공지와 겹치는 일정은 저장·알림 모두 하나만 ⑤ 알림은 2일 이내 공지의 일정만."""
import json
import logging

import pytest
import requests

import main as app
from conftest import make_response
from fakeclaude import KEY, MODEL, SECRET_BODY, FakePost, error_reply, ev, events_reply, reply
from test_main import Clock, Net, T1, data_dir, read  # noqa: F401  (data_dir은 test_main의 fixture)
from updater import config

LONG = "공지 본문입니다. " * 10
ENV = {config.ANTHROPIC_API_KEY_ENV: KEY}


class NoticeNet(Net):
    """Net에 공지 상세 페이지(stellive.me/news/<번호>)를 더한 가짜. pages[번호]로 본문을 바꾸고 detail_fail[번호]로 실패시킨다."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.pages, self.detail_fail = {}, {}

    def __call__(self, url, **kw):
        if url.startswith("https://stellive.me/news/"):
            self.calls.append(url)
            num = url.rsplit("/", 1)[1]
            if num in self.detail_fail:
                raise self.detail_fail[num]
            return make_response(200, f"<html><body><div class='xe_content'><p>{self.pages.get(num, LONG)}</p></div></body></html>")
        return super().__call__(url, **kw)


def write_news(data_dir, *notices):
    items = [{"id": f"sl-{n}", "date": d, "added": T1, "cat": "공지", "who": ["all"], "title": f"공지 {n}", "url": f"https://stellive.me/news/{n}",
              "source": "공식 홈페이지"} for n, d in notices]
    (data_dir / "news.json").write_text(json.dumps({"updatedAt": "2026-10-06T09:00:00+09:00", "items": items}, ensure_ascii=False), encoding="utf-8")


def write_events(data_dir, doc):
    (data_dir / "auto_events.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def go(data_dir, net, post, *argv, environ=None, clock=T1, dry=True):
    args = [*(["--dry-run"] if dry else []), "--only", "events", "--local-state", *argv]
    return app.main(args, get=net, claude_post=post, data_dir=data_dir, now=Clock(clock), sleep=lambda s: None, environ=ENV if environ is None else environ)


def popup(start="2026-10-23", **kw):
    return ev("popup", "STELLA MODE:ON 팝업스토어", start, **kw)


# ---------------------------------------------------------------- 키가 없을 때
def test_without_a_key_the_stage_is_skipped_and_the_previous_events_are_written_back_unchanged(data_dir, caplog):
    """배포는 site/ 전체를 올린다. auto_events.json을 안 쓰면 저장소의 빈 시드가 배포본의 누적 일정·처리 기록을 덮어쓴다."""
    prior = {"updatedAt": "2026-10-05T10:00:00+09:00", "processed": {"sl-9": {"at": "2026-10-05T10:00:00+09:00", "result": "events", "tries": 1}},
             "items": [{"id": "auto-sl-9-1", "source": "sl-9", "kind": "popup", "title": "이전 일정", "start": "2026-10-23", "who": ["all"], "url": "https://stellive.me/news/9"}]}
    write_events(data_dir, prior)
    write_news(data_dir, (14044, "2026-10-05"))
    net, post = NoticeNet(), FakePost(events_reply(popup()))
    assert go(data_dir, net, post, environ={}) == 0
    assert read(data_dir, "auto_events") == prior  # updatedAt까지 그대로
    assert post.calls == [] and net.calls_to("https://stellive.me/news/") == []
    assert f"{config.ANTHROPIC_API_KEY_ENV}가 없어" in caplog.text


def test_a_blank_key_counts_as_no_key(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    post = FakePost(events_reply(popup()))
    assert go(data_dir, NoticeNet(), post, environ={config.ANTHROPIC_API_KEY_ENV: "   "}) == 0 and post.calls == []


# ---------------------------------------------------------------- 정상 흐름
def test_a_run_extracts_events_from_notices_and_writes_auto_events(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    net = NoticeNet()
    post = FakePost(events_reply(popup(end="2026-11-01", time="10:00–20:00", place="서울 광진구 광나루로 441"), ev("reservation", "팝업 예약 오픈", "2026-10-12T20:00+09:00")))
    assert go(data_dir, net, post) == 0
    doc = read(data_dir, "auto_events")
    assert doc["updatedAt"] == T1 and doc["processed"] == {"sl-14044": {"at": T1, "result": "events", "tries": 1}}
    assert [(i["id"], i["kind"], i["start"]) for i in doc["items"]] == [("auto-sl-14044-2", "reservation", "2026-10-12T20:00:00+09:00"), ("auto-sl-14044-1", "popup", "2026-10-23")]
    assert all(i["url"] == "https://stellive.me/news/14044" for i in doc["items"])
    assert len(post.calls) == 1 and net.calls_to("https://stellive.me/news/") == ["https://stellive.me/news/14044"]


def test_the_request_to_claude_uses_the_key_header_the_default_model_and_the_claude_timeout(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    post = FakePost(events_reply())
    go(data_dir, NoticeNet(), post)
    (url, payload, headers, timeout), = post.calls
    assert url == config.CLAUDE_API_URL and headers["x-api-key"] == KEY and timeout == 30
    assert payload["model"] == config.CLAUDE_DEFAULT_MODEL and payload["max_tokens"] == 800
    assert KEY not in url and KEY not in json.dumps(payload, ensure_ascii=False)


def test_the_model_can_be_changed_by_an_environment_variable(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    post = FakePost(events_reply())
    go(data_dir, NoticeNet(), post, environ={**ENV, config.CLAUDE_MODEL_ENV: "claude-custom-model"})
    assert post.calls[0][1]["model"] == "claude-custom-model"


def test_the_summary_line_is_logged_with_counts_and_the_model_the_api_reported(data_dir, caplog):
    write_news(data_dir, (14044, "2026-10-05"), (14028, "2026-10-04"))
    net = NoticeNet()
    net.pages["14028"] = "짧음"  # 이미지 위주 공지
    with caplog.at_level(logging.INFO):
        go(data_dir, net, FakePost(events_reply(popup())))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("일정 추출:"))
    for part in ("대상 2개", "events 1", "no_text 1", "API 호출 1회", f"모델 {MODEL}"):
        assert part in line, part


def test_second_run_on_the_same_state_makes_no_requests(data_dir):
    write_news(data_dir, (14044, "2026-10-05"), (14028, "2026-10-04"))
    net, post = NoticeNet(), FakePost(events_reply(popup()))
    go(data_dir, net, post)
    n_net, n_post = len(net.calls), len(post.calls)
    assert go(data_dir, net, post, clock="2026-10-06T10:30:00+09:00") == 0
    assert (len(net.calls), len(post.calls)) == (n_net, n_post)


def test_at_most_five_notices_per_run(data_dir):
    write_news(data_dir, *[(100 + i, f"2026-10-0{i}") for i in range(1, 7)])
    post = FakePost(*[events_reply(popup(start=f"2026-10-{20 + i}")) for i in range(6)])
    go(data_dir, NoticeNet(), post)
    assert len(post.calls) == 5 and len(read(data_dir, "auto_events")["processed"]) == 5
    go(data_dir, NoticeNet(), post, clock="2026-10-06T10:30:00+09:00")
    assert len(post.calls) == 6


def test_only_events_does_not_rewrite_the_news_or_status_files_and_does_not_fail(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")}
    assert go(data_dir, NoticeNet(), FakePost(events_reply())) == 0  # 수집기를 안 돌려도 '모든 소스 실패'로 중단하지 않는다
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in before} == before


def test_events_is_an_enabled_stage_by_default_but_not_a_collector():
    assert "events" in config.ENABLED_SOURCES and "events" not in app.SOURCES
    args = app.parse_args([])
    assert args.events and args.sources == list(app.SOURCES)
    assert app.parse_args(["--only", "events"]).events and app.parse_args(["--only", "events"]).sources == []
    assert not app.parse_args(["--only", "news"]).events
    with pytest.raises(SystemExit):
        app.parse_args(["--only", "nope"])


def test_a_full_run_without_a_key_still_succeeds_and_keeps_the_seed(data_dir):
    """키가 아직 없는 첫 배포: 기존 소스는 모두 정상, 일정 단계만 건너뛴다."""
    net = NoticeNet()
    assert app.main(["--dry-run"], get=net, claude_post=FakePost(events_reply()), data_dir=data_dir, now=Clock(T1), sleep=lambda s: None, environ={}) == 0
    assert read(data_dir, "auto_events") == {"updatedAt": None, "processed": {}, "items": []}
    assert net.calls_to("https://stellive.me/news/") == []


# ---------------------------------------------------------------- 오류
@pytest.mark.parametrize("outcome,label", [
    (error_reply(401, "authentication_error"), "HTTP 401 authentication_error"),
    (error_reply(400, "invalid_request_error"), "HTTP 400 invalid_request_error"),
    (error_reply(529, "overloaded_error"), "HTTP 529 overloaded_error"),
    (requests.ConnectionError(f"boom {KEY}"), "ConnectionError"),
])
def test_api_errors_never_fail_the_run_and_never_use_up_the_retries(data_dir, outcome, label, caplog):
    write_news(data_dir, (14044, "2026-10-05"), (14028, "2026-10-04"))
    prior = read(data_dir, "auto_events")
    post = FakePost(outcome)
    assert go(data_dir, NoticeNet(), post) == 0
    doc = read(data_dir, "auto_events")
    assert doc["processed"] == {} and doc["items"] == prior["items"] and len(post.calls) == 1  # 기록 없음, 첫 오류에서 멈춤
    assert label in caplog.text and KEY not in caplog.text and SECRET_BODY not in caplog.text
    assert go(data_dir, NoticeNet(), FakePost(events_reply()), clock="2026-10-06T10:30:00+09:00") == 0  # 다음 실행은 처음부터 다시 시도
    assert len(read(data_dir, "auto_events")["processed"]) == 2


def test_a_rejected_key_is_surfaced_as_an_actions_warning_without_the_key(data_dir, capsys):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(error_reply(401, "authentication_error", f"bad {KEY}")), environ={**ENV, "GITHUB_ACTIONS": "true"})
    out = capsys.readouterr().out
    assert "::warning title=Claude API::Claude API 키 확인 필요 (HTTP 401 authentication_error)" in out and KEY not in out and SECRET_BODY not in out


def test_a_rejected_request_is_surfaced_too_but_a_transient_error_is_only_logged(data_dir, capsys):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(error_reply(400, "invalid_request_error")), environ={**ENV, "GITHUB_ACTIONS": "true"})
    assert "::warning title=Claude API::Claude API가 요청을 거부했습니다 (HTTP 400 invalid_request_error)" in capsys.readouterr().out
    go(data_dir, NoticeNet(), FakePost(error_reply(529, "overloaded_error")), environ={**ENV, "GITHUB_ACTIONS": "true"})
    assert "::warning" not in capsys.readouterr().out


def test_an_unexpected_crash_in_the_stage_keeps_the_previous_events_and_the_run_succeeds(data_dir, caplog, monkeypatch):
    write_news(data_dir, (14044, "2026-10-05"))
    prior = read(data_dir, "auto_events")

    def boom(*a, **k):
        raise RuntimeError(f"unexpected {KEY} {SECRET_BODY}")

    monkeypatch.setattr(app.auto_events, "run", boom)
    assert go(data_dir, NoticeNet(), FakePost(events_reply())) == 0
    assert read(data_dir, "auto_events") == prior
    assert "RuntimeError" in caplog.text and KEY not in caplog.text and SECRET_BODY not in caplog.text


def test_a_claude_key_hidden_in_an_exception_is_masked_in_the_logs(data_dir, caplog):
    """우리 코드가 키를 메시지에 넣지 않더라도, 예상 밖 경로(다른 소스의 예외 메시지)로 새면 main이 등록해 둔 키를 가린다 (마지막 방어선)."""
    class LeakyNews(NoticeNet):
        def __call__(self, url, **kw):
            if url == config.NEWS_URL:
                raise RuntimeError(f"unexpected {KEY}")
            return super().__call__(url, **kw)

    write_news(data_dir, (14044, "2026-10-05"))
    with caplog.at_level(logging.DEBUG):
        app.main(["--dry-run", "--only", "news,events", "--local-state"], get=LeakyNews(), claude_post=FakePost(events_reply()), data_dir=data_dir,
                 now=Clock(T1), sleep=lambda s: None, environ=ENV)
    assert "소스 news 실패" in caplog.text and KEY not in caplog.text and "***" in caplog.text


def test_a_failing_detail_page_does_not_fail_the_run(data_dir):
    write_news(data_dir, (14044, "2026-10-05"), (14028, "2026-10-04"))
    net = NoticeNet()
    net.detail_fail["14044"] = requests.ConnectionError("down")
    assert go(data_dir, net, FakePost(events_reply(popup()))) == 0
    assert list(read(data_dir, "auto_events")["processed"]) == ["sl-14028"]  # 일시 오류는 기록하지 않고 다음 실행에 다시


def test_the_key_never_reaches_any_output_file_or_the_console(data_dir, capsys, caplog):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(reply("모르겠어요"), reply("???")))  # 출력 깨짐 → error 기록
    shown = capsys.readouterr().out + capsys.readouterr().err + caplog.text + "".join(p.read_text(encoding="utf-8") for p in data_dir.glob("*.json"))
    assert KEY not in shown and "모르겠어요" not in shown
    assert read(data_dir, "auto_events")["processed"]["sl-14044"]["result"] == "error"


# ---------------------------------------------------------------- 알림
def alerts_in_file():
    path = config.ALERTS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def event_embeds(doc):
    return [e for m in doc["messages"] for e in m["embeds"] if "일정 추가" in e["author"]["name"]]


def test_a_new_event_from_a_recent_notice_leaves_an_event_alert_in_the_alerts_file(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(events_reply(popup(end="2026-11-01", place="서울"), ev("goods", "굿즈 마감", "2026-10-30"), ev("other", "콜라보", "2026-10-24"))), dry=False)
    (e,) = event_embeds(alerts_in_file())  # popup만 (goods·other는 알리지 않는다)
    assert e["title"] == "STELLA MODE:ON 팝업스토어" and e["description"] == "10/23(금) ~ 11/1(일) · 서울" and e["url"] == "https://stellive.me/news/14044"
    assert read(data_dir, "auto_events")["items"].__len__() == 3  # 알림이 아니어도 일정은 모두 저장된다
    assert KEY not in config.ALERTS_FILE.read_text(encoding="utf-8")


def test_events_from_old_notices_are_stored_but_not_alerted(data_dir):
    write_news(data_dir, (14000, "2026-10-01"))  # 5일 전 공지
    go(data_dir, NoticeNet(), FakePost(events_reply(popup())), dry=False)
    assert len(read(data_dir, "auto_events")["items"]) == 1 and alerts_in_file() is None


def test_the_same_popup_in_two_recent_notices_is_stored_once_and_alerted_once(data_dir):
    write_news(data_dir, (14044, "2026-10-05"), (14028, "2026-10-04"))
    post = FakePost(events_reply(popup(end="2026-11-01")), events_reply(ev("popup", "팝업스토어 이용 안내", "2026-10-23", end="2026-11-01")))
    go(data_dir, NoticeNet(), post, dry=False)
    doc = read(data_dir, "auto_events")
    assert [i["source"] for i in doc["items"]] == ["sl-14028"] and len(post.calls) == 2  # 먼저 처리된(오래된, 번호가 작은) 공지의 것 하나
    assert len(event_embeds(alerts_in_file())) == 1
    assert {r["result"] for r in doc["processed"].values()} == {"events"}


def test_dry_run_prints_the_event_alert_and_leaves_no_file(data_dir, capsys):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(events_reply(popup())))
    out = capsys.readouterr().out
    assert "📅 일정 추가" in out and "설명: 10/23(금)" in out and alerts_in_file() is None


def test_no_discord_flag_leaves_no_alert_but_still_stores_the_events(data_dir):
    write_news(data_dir, (14044, "2026-10-05"))
    go(data_dir, NoticeNet(), FakePost(events_reply(popup())), "--no-discord", dry=False)
    assert alerts_in_file() is None and len(read(data_dir, "auto_events")["items"]) == 1
