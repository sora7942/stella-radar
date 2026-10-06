"""send_alerts.py: 배포 성공 뒤에 알림 파일만 읽어 발송. 전부 가짜 post — 네트워크·실제 디스코드 호출 없음.
웹훅 URL은 비밀이라 어떤 경로로도 출력·로그에 새지 않는지를 확인한다."""
import json

import pytest
import requests

import send_alerts
from conftest import make_response
from updater import config, discord

HOOK = "https://discord.com/api/webhooks/123456789/SECRET-TOKEN-abcdef"
ENV = {"DISCORD_WEBHOOK_URL": HOOK}
SITE = "https://sora7942.github.io/stella-radar/"


def make_messages(n=3):
    members = {"members": {"lize": {"n": "아카네 리제", "c": "#C8352E"}}, "groups": []}
    alerts = [{"kind": "video", "cat": "영상", "who": ["lize"], "title": f"영상 {i}", "url": f"https://example.invalid/{i}",
               "date": "2026-10-06T11:00:00+09:00", "yt": f"V{i}"} for i in range(n)]
    return discord.build_messages(alerts, members, site_url=SITE)


def write_alerts(path, messages=None, **extra):
    messages = make_messages() if messages is None else messages
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"createdAt": "2026-10-06T11:00:00+09:00", "alertCount": 3, "messages": messages, **extra}, ensure_ascii=False), encoding="utf-8")


class Post:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, url, payload, **kw):
        self.calls.append((url, payload))
        out = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(out, Exception):
            raise out
        return make_response(204)


def run(post, *argv, env=ENV, path=None):
    return send_alerts.main(list(argv), post=post, sleep=lambda s: None, alerts_file=path or config.ALERTS_FILE, environ=env)


def leaked(*texts):
    return any("SECRET" in t or "webhooks" in t for t in texts)


# ============================ 보낼 것이 없을 때 ================================
def test_no_alerts_file_means_nothing_to_send(caplog):
    post = Post()
    with caplog.at_level("INFO"):
        assert run(post) == 0
    assert post.calls == [] and "보낼 알림이 없습니다" in caplog.text


def test_an_empty_message_list_sends_nothing():
    write_alerts(config.ALERTS_FILE, messages=[])
    post = Post()
    assert run(post) == 0 and post.calls == []


# ============================ 보내기 =========================================
def test_sends_exactly_the_messages_in_the_file_in_order_then_removes_it(caplog, capsys):
    messages = make_messages(15)  # 10 + 5
    write_alerts(config.ALERTS_FILE, messages)
    post = Post()
    with caplog.at_level("DEBUG"):
        assert run(post) == 0
    assert [(u, p) for u, p in post.calls] == [(HOOK, m) for m in messages]  # 파일 내용 그대로, 순서대로
    assert not config.ALERTS_FILE.exists()  # 시도한 알림은 다시 보내지 않는다
    out = capsys.readouterr()
    assert "메시지 2개 발송, 0개 실패 (알림 15건)" in caplog.text and not leaked(caplog.text, out.out, out.err)


def test_running_it_again_does_not_send_twice():
    write_alerts(config.ALERTS_FILE)
    first, second = Post(), Post()
    run(first)
    run(second)
    assert len(first.calls) == 1 and second.calls == []


def test_it_needs_nothing_but_the_alerts_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # site/data도 members.json도 없는 곳에서
    path = tmp_path / "somewhere" / "alerts.json"
    write_alerts(path)
    post = Post()
    assert run(post, path=path) == 0 and len(post.calls) == 1


def test_default_alerts_file_comes_from_config_at_call_time():
    write_alerts(config.ALERTS_FILE)
    post = Post()
    assert send_alerts.main([], post=post, sleep=lambda s: None, environ=ENV) == 0 and len(post.calls) == 1


def test_extra_fields_in_the_file_are_not_sent():
    write_alerts(config.ALERTS_FILE, secretish="이건 보내지 않는다")
    post = Post()
    run(post)
    assert "secretish" not in json.dumps(post.calls[0][1], ensure_ascii=False)


# ============================ 웹훅이 없을 때 ===================================
def test_without_a_webhook_it_warns_and_keeps_the_file(caplog, capsys):
    write_alerts(config.ALERTS_FILE)
    post = Post()
    with caplog.at_level("INFO"):
        assert run(post, env={}) == 0
    assert post.calls == [] and config.ALERTS_FILE.exists()  # 웹훅을 설정한 뒤 다시 돌릴 수 있게
    assert "DISCORD_WEBHOOK_URL이 없어 알림 3건을 보내지 못했습니다" in caplog.text
    assert "::warning" not in capsys.readouterr().out  # Actions가 아니면 주석을 내지 않는다


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_webhook_counts_as_missing(blank, caplog):
    write_alerts(config.ALERTS_FILE)
    post = Post()
    assert run(post, env={"DISCORD_WEBHOOK_URL": blank}) == 0 and post.calls == []


def test_on_github_actions_a_missing_secret_is_surfaced_as_an_annotation(capsys):
    write_alerts(config.ALERTS_FILE)
    assert run(Post(), env={"GITHUB_ACTIONS": "true"}) == 0
    out = capsys.readouterr().out
    assert "::warning title=디스코드 알림::DISCORD_WEBHOOK_URL이 없어 알림 3건을 보내지 못했습니다" in out and not leaked(out)


# ============================ 발송 실패 ======================================
def http_error(status):
    return requests.HTTPError(f"{status} Error for url: {HOOK}", response=make_response(status))


def test_failures_never_fail_the_run_and_never_leak_the_url(caplog, capsys):
    write_alerts(config.ALERTS_FILE, make_messages(15))
    post = Post(requests.ConnectionError(f"boom {HOOK}"), http_error(500))
    with caplog.at_level("DEBUG"):
        assert run(post, env={**ENV, "GITHUB_ACTIONS": "true"}) == 0  # 배포는 이미 끝났다 → 항상 0
    out = capsys.readouterr()
    assert not leaked(caplog.text, out.out, out.err)
    assert "메시지 0개 발송, 2개 실패" in caplog.text
    assert "::warning title=디스코드 알림::디스코드 메시지 2개를 보내지 못했습니다" in out.out  # 실행 요약에서 보이게
    assert not config.ALERTS_FILE.exists()  # 실패한 알림도 다시 보내지 않는다 (at-most-once)


def test_a_partial_failure_still_sends_the_rest(caplog):
    write_alerts(config.ALERTS_FILE, make_messages(15))
    post = Post(http_error(500), None)
    with caplog.at_level("INFO"):
        assert run(post) == 0
    assert len(post.calls) == 2 and "메시지 1개 발송, 1개 실패" in caplog.text


def test_a_file_that_cannot_be_removed_only_warns(monkeypatch, capsys):
    write_alerts(config.ALERTS_FILE)

    def deny(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(type(config.ALERTS_FILE), "unlink", deny)
    assert run(Post(), env={**ENV, "GITHUB_ACTIONS": "true"}) == 0
    assert "알림 파일을 지우지 못했습니다" in capsys.readouterr().out


# ============================ dry-run ========================================
def test_dry_run_prints_the_content_without_sending_or_needing_a_webhook(capsys):
    write_alerts(config.ALERTS_FILE)
    post = Post()
    assert run(post, "--dry-run", env={}) == 0
    out = capsys.readouterr().out
    assert post.calls == [] and config.ALERTS_FILE.exists()  # 보내지도 지우지도 않는다
    assert "[디스코드 dry-run] 알림 3건" in out and "영상 0" in out and not leaked(out)


# ============================ 이상한 파일 =====================================
@pytest.mark.parametrize("content", [
    "이건 JSON이 아님",
    "[]",
    json.dumps({"messages": "list가 아님"}),
    json.dumps({"nothing": 1}),
    json.dumps({"messages": [{"embeds": []}]}),                              # 빈 임베드
    json.dumps({"messages": [{"embeds": [{}] * 11}]}),                       # 한 메시지에 11개
    json.dumps({"messages": [{"embeds": [{}]}] * 3}),                        # 3메시지 (상한 2)
    json.dumps({"messages": [{"embeds": ["문자열"]}]}),
    json.dumps({"messages": ["문자열"]}),
])
def test_a_malformed_file_is_never_sent(content, caplog, capsys):
    config.ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.ALERTS_FILE.write_text(content, encoding="utf-8")
    post = Post()
    with caplog.at_level("INFO"):
        assert run(post, env={**ENV, "GITHUB_ACTIONS": "true"}) == 0
    assert post.calls == [] and config.ALERTS_FILE.exists()  # 보내지 않고, 살펴볼 수 있게 남긴다
    assert "알림 파일을 읽을 수 없어 보내지 않습니다" in caplog.text and "::warning" in capsys.readouterr().out


def test_an_unreadable_encoding_is_handled():
    config.ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.ALERTS_FILE.write_bytes(b"\xff\xfe\x00bad")
    post = Post()
    assert run(post) == 0 and post.calls == []
