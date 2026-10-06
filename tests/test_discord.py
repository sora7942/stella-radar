"""디스코드 임베드·메시지 분할·발송. 전부 가짜 post — 네트워크·실제 디스코드 호출 없음.
웹훅 URL은 비밀이라, 성공·실패 어느 경로로도 출력·로그에 새지 않는지를 확인한다."""
import json

import pytest
import requests

from conftest import make_response
from updater import config, discord

SECRET_URL = "https://discord.com/api/webhooks/123456789/SECRET-TOKEN-abcdef"
SITE = "https://sora7942.github.io/stella-radar/"


@pytest.fixture
def members(members):  # conftest의 실제 members.json
    return members


def alert(kind="video", who=("lize",), title="제목", **kw):
    base = {"kind": kind, "cat": {"video": "영상", "notice": "공지", "music": "음악", "live": "방송"}[kind], "who": list(who),
            "title": title, "url": "https://example.invalid/x", "date": "2026-10-06T11:00:00+09:00", "yt": None}
    return {**base, **kw}


# ============================ 이름·색 =========================================
def test_names_members_groups_and_all(members):
    assert discord.names_of(["lize"], members) == "아카네 리제"
    assert discord.names_of(["rin", "nana"], members) == "아오쿠모 린, 하나코 나나"
    assert discord.names_of(["everys"], members) == "에버리스"
    assert discord.names_of(["all"], members) == "스텔라이브"
    assert discord.names_of(["cliche", "riko"], members) == "클리셰, 유즈하 리코"


def test_names_fall_back_to_stellive_and_are_shortened(members):
    assert discord.names_of([], members) == discord.names_of(["unknown"], members) == "스텔라이브"
    many = ["yuni", "huya", "hina", "mashiro", "lize"]
    assert discord.names_of(many, members) == "아야츠노 유니, 사키하네 후야, 시라유키 히나 외 2명"


def test_color_is_the_first_members_color_else_default(members):
    assert discord.color_of(["lize"], members) == 0xC8352E
    assert discord.color_of(["everys", "tabi"], members) == 0x2C9A78  # 그룹은 색이 없으니 멤버를 찾는다
    assert discord.color_of(["all"], members) == config.DISCORD_DEFAULT_COLOR
    assert discord.color_of(["cliche"], members) == config.DISCORD_DEFAULT_COLOR
    assert discord.color_of(["bad"], {"members": {"bad": {"c": "red"}}}) == config.DISCORD_DEFAULT_COLOR


# ============================ 임베드 ==========================================
def test_video_embed_has_link_member_color_and_thumbnail(members):
    e = discord.build_embed(alert("video", title="새 영상", yt="VID123", url="https://www.youtube.com/watch?v=VID123"), members)
    assert e["title"] == "새 영상" and e["url"] == "https://www.youtube.com/watch?v=VID123"
    assert e["author"]["name"] == "아카네 리제 · 영상" and e["color"] == 0xC8352E
    assert e["thumbnail"] == {"url": "https://i.ytimg.com/vi/VID123/mqdefault.jpg"}  # 핫링크. 이미지를 저장하지 않는다
    assert e["timestamp"] == "2026-10-06T11:00:00+09:00"


def test_non_video_embed_has_no_thumbnail_and_date_only_has_no_timestamp(members):
    e = discord.build_embed(alert("notice", who=["all"], cat="굿즈", date="2026-10-05"), members)
    assert "thumbnail" not in e and "timestamp" not in e
    assert e["author"]["name"] == "스텔라이브 · 굿즈"  # 공지는 카테고리(공지·굿즈·이벤트)를 보여 준다
    assert e["color"] == config.DISCORD_DEFAULT_COLOR


def test_live_embed_uses_broadcast_title_or_a_fallback(members):
    e = discord.build_embed(alert("live", title="오늘의 방송", url="https://chzzk.naver.com/live/x"), members)
    assert e["title"] == "오늘의 방송" and e["author"]["name"] == "아카네 리제 · 방송 시작" and "thumbnail" not in e
    assert discord.build_embed(alert("live", title=""), members)["title"] == "아카네 리제 방송 시작"


def test_music_embed_label(members):
    assert discord.build_embed(alert("music", who=["riko"], yt="V"), members)["author"]["name"] == "유즈하 리코 · 음악"


def test_missing_url_is_omitted_not_null(members):
    e = discord.build_embed(alert("live", url=None), members)
    assert "url" not in e


def test_long_titles_are_clipped_to_the_discord_limit(members):
    e = discord.build_embed(alert(title="가" * 400), members)
    assert len(e["title"]) == 256 and e["title"].endswith("…")


# ============================ 메시지 분할 ======================================
def alerts_n(n, kind="video"):
    return [alert(kind, title=f"영상 {i}") for i in range(n)]


def test_no_alerts_no_messages(members):
    assert discord.build_messages([], members, site_url=SITE) == []


@pytest.mark.parametrize("n, sizes", [(1, [1]), (10, [10]), (11, [10, 1]), (20, [10, 10])])
def test_ten_embeds_per_message_up_to_two_messages(members, n, sizes):
    msgs = discord.build_messages(alerts_n(n), members, site_url=SITE)
    assert [len(m["embeds"]) for m in msgs] == sizes
    assert all("content" not in m for m in msgs)  # 상한 안이면 "외 N건"이 없다


def test_over_twenty_adds_the_remainder_note_to_the_last_message(members):
    msgs = discord.build_messages(alerts_n(27), members, site_url=SITE)
    assert [len(m["embeds"]) for m in msgs] == [10, 10]
    assert "content" not in msgs[0] and msgs[1]["content"] == f"외 7건 더 있어요 → {SITE}"
    assert [e["title"] for m in msgs for e in m["embeds"]] == [f"영상 {i}" for i in range(20)]  # 앞(우선순위 높은) 20건


def test_exactly_twenty_one_says_one_more(members):
    assert discord.build_messages(alerts_n(21), members, site_url=SITE)[-1]["content"].startswith("외 1건")


def test_mentions_are_disabled_on_every_message(members):
    msgs = discord.build_messages([alert(title="@everyone 공지")], members, site_url=SITE)
    assert msgs[0]["allowed_mentions"] == {"parse": []}


def test_payload_is_json_serializable_and_has_no_secret(members):
    msgs = discord.build_messages(alerts_n(3), members, site_url=SITE)
    text = json.dumps(msgs, ensure_ascii=False)
    assert "SECRET" not in text and "webhooks" not in text


# ============================ dry-run 출력 ====================================
def test_dry_run_text_shows_every_embed_and_never_the_webhook(members):
    msgs = discord.build_messages(
        [alert("live", title="방송 제목"), alert("video", who=["rin"], title="영상", yt="VID")] + alerts_n(20), members, site_url=SITE)
    text = discord.format_dry_run(msgs)
    assert text.startswith("[디스코드 dry-run] 알림 20건 → 메시지 2개 (보내지 않음)")
    assert "아카네 리제 · 방송 시작" in text and "제목: 방송 제목" in text and "색 #C8352E" in text
    assert "썸네일 https://i.ytimg.com/vi/VID/mqdefault.jpg" in text and "본문: 외 2건 더 있어요" in text
    assert "SECRET" not in text and "webhooks" not in text


# ============================ 발송 ============================================
class Post:
    """http.post_json 대용: 호출을 기록하고, 미리 정한 결과(예외 또는 None)를 순서대로 낸다."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, url, payload, **kw):
        self.calls.append((url, payload, kw))
        out = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(out, Exception):
            raise out
        return make_response(204)


def http_error(status, body=b""):
    resp = make_response(status, body)
    return requests.HTTPError(f"{status} Client Error for url: {SECRET_URL}", response=resp)


def test_send_posts_each_message_in_order_with_a_pause_between(members):
    msgs = discord.build_messages(alerts_n(15), members, site_url=SITE)
    post, sleeps = Post(), []
    assert discord.send(SECRET_URL, msgs, post=post, sleep=sleeps.append) == (2, 0)
    assert [c[0] for c in post.calls] == [SECRET_URL, SECRET_URL] and [c[1] for c in post.calls] == msgs
    assert sleeps == [config.DISCORD_MESSAGE_DELAY]  # 첫 메시지 전에는 쉬지 않는다


def test_a_failed_message_does_not_stop_the_next_one(members, caplog):
    msgs = discord.build_messages(alerts_n(15), members, site_url=SITE)
    post = Post(http_error(500), None)
    with caplog.at_level("INFO"):
        assert discord.send(SECRET_URL, msgs, post=post, sleep=lambda s: None) == (1, 1)
    assert len(post.calls) == 2 and "HTTP 500" in caplog.text


@pytest.mark.parametrize("exc", [requests.ConnectionError(f"boom {SECRET_URL}"), requests.Timeout(f"slow {SECRET_URL}"), http_error(404)])
def test_failures_are_logged_without_the_webhook_url(members, caplog, capsys, exc):
    # 실제 requests 예외 메시지에는 URL이 들어 있다 → 종류와 상태만 기록해야 한다
    with caplog.at_level("DEBUG"):
        assert discord.send(SECRET_URL, discord.build_messages(alerts_n(1), members, site_url=SITE), post=Post(exc), sleep=lambda s: None) == (0, 1)
    out = capsys.readouterr()
    assert "SECRET" not in caplog.text + out.out + out.err and "webhooks" not in caplog.text
    assert "디스코드 발송 실패" in caplog.text


def test_429_waits_the_requested_time_then_retries_once(members, caplog):
    msgs = discord.build_messages(alerts_n(1), members, site_url=SITE)
    post, sleeps = Post(http_error(429, json.dumps({"retry_after": 1.5}).encode()), None), []
    with caplog.at_level("INFO"):
        assert discord.send(SECRET_URL, msgs, post=post, sleep=sleeps.append) == (1, 0)
    assert sleeps == [1.5] and len(post.calls) == 2 and "SECRET" not in caplog.text


def test_429_twice_gives_up_after_one_retry(members):
    msgs = discord.build_messages(alerts_n(1), members, site_url=SITE)
    body = json.dumps({"retry_after": 1}).encode()
    post = Post(http_error(429, body), http_error(429, body))
    assert discord.send(SECRET_URL, msgs, post=post, sleep=lambda s: None) == (0, 1) and len(post.calls) == 2


def test_429_with_a_huge_wait_is_not_waited_for(members):
    msgs = discord.build_messages(alerts_n(1), members, site_url=SITE)
    post, sleeps = Post(http_error(429, json.dumps({"retry_after": 600}).encode())), []
    assert discord.send(SECRET_URL, msgs, post=post, sleep=sleeps.append) == (0, 1)
    assert sleeps == [] and len(post.calls) == 1  # 몇 분씩 실행을 붙잡지 않는다


def test_429_wait_can_come_from_the_header(members):
    resp = make_response(429, b"not json")
    resp.headers["Retry-After"] = "2"
    post, sleeps = Post(requests.HTTPError("429", response=resp), None), []
    assert discord.send(SECRET_URL, discord.build_messages(alerts_n(1), members, site_url=SITE), post=post, sleep=sleeps.append) == (1, 0)
    assert sleeps == [2.0]


def test_429_without_any_wait_hint_is_a_failure(members):
    post = Post(http_error(429, b"not json"))
    assert discord.send(SECRET_URL, discord.build_messages(alerts_n(1), members, site_url=SITE), post=post, sleep=lambda s: None) == (0, 1)
    assert len(post.calls) == 1


def test_default_post_goes_through_http_post_json():
    import inspect
    assert inspect.signature(discord.send).parameters["post"].default.__name__ == "post_json"  # timeout=10·User-Agent 강제 통로
