"""'일정 추가' 알림 규칙 (기능 3, SPEC-v1.1 알림): 순수 함수라 가짜 시계만 있으면 된다. 네트워크 없음."""
import pytest

from updater import alerts, config, discord, timeutil

NOW = timeutil.parse_kst("2026-10-09T13:00:00+09:00")
NEWS = [{"id": "sl-1", "date": "2026-10-09"}, {"id": "sl-old", "date": "2026-10-06"}, {"id": "sl-2days", "date": "2026-10-07"}, {"id": "sl-3days", "date": "2026-10-06"}]


def event(kind="popup", start="2026-10-23", source="sl-1", **kw):
    return {"id": f"auto-{source}-1", "source": source, "kind": kind, "title": "STELLA MODE:ON 팝업스토어", "start": start, "who": ["all"],
            "url": f"https://stellive.me/news/{source[3:]}", **kw}


def got(*events, news=NEWS, now=NOW):
    return alerts.event_alerts(list(events), news, now)


# ---------------------------------------------------------------- 어떤 일정이 알림이 되는가
@pytest.mark.parametrize("kind", ["popup", "concert", "reservation", "broadcast"])
def test_alert_kinds_are_popup_concert_reservation_and_broadcast(kind):
    assert len(got(event(kind))) == 1


@pytest.mark.parametrize("kind", ["goods", "other", "party", None])
def test_goods_and_other_never_alert(kind):
    assert got(event(kind)) == []


def test_alert_kinds_live_in_config():
    assert config.EVENT_ALERT_KINDS == ("popup", "concert", "reservation", "broadcast")


@pytest.mark.parametrize("start,expected", [
    ("2026-10-10", True), ("2026-10-09", True),  # 날짜만이면 오늘 포함
    ("2026-10-08", False),
    ("2026-10-09T13:00:01+09:00", True), ("2026-10-09T13:00:00+09:00", False), ("2026-10-09T12:59:00+09:00", False),  # 시각이 있으면 지금 이후만
])
def test_start_must_be_in_the_future(start, expected):
    assert bool(got(event(start=start))) is expected


@pytest.mark.parametrize("source,expected", [("sl-1", True), ("sl-2days", True), ("sl-3days", False), ("sl-unknown", False)])
def test_the_source_notice_must_be_within_two_days(source, expected):
    """최초 채우기·늦은 재시도 때 오래된 공지의 일정이 한꺼번에 알림이 되지 않게 — 출처 공지가 2일 이내일 때만."""
    assert config.ALERT_NOTICE_DAYS == 2
    assert bool(got(event(source=source))) is expected


def test_a_source_without_a_date_is_not_alerted():
    assert got(event(), news=[{"id": "sl-1"}]) == []


def test_unreadable_events_are_skipped_not_fatal(caplog):
    assert got({"id": "x", "kind": "popup", "source": "sl-1"}, event(start="내일")) == []
    assert "일정을 읽을 수 없어" in caplog.text


# ---------------------------------------------------------------- 알림 내용
def test_alert_dict_carries_title_url_who_and_a_description():
    (a,) = got(event(end="2026-11-01", time="10:00–20:00", place="서울 광진구 광나루로 441"))
    assert a == {"kind": "event", "cat": "일정", "who": ["all"], "title": "STELLA MODE:ON 팝업스토어", "url": "https://stellive.me/news/1",
                 "date": None, "yt": None, "description": "10/23(금) ~ 11/1(일) · 10:00–20:00 · 서울 광진구 광나루로 441"}


@pytest.mark.parametrize("ev,text", [
    (dict(start="2026-10-23", end="2026-11-01", time="10:00–20:00", place="서울 광진구"), "10/23(금) ~ 11/1(일) · 10:00–20:00 · 서울 광진구"),
    (dict(start="2026-10-07"), "10/7(수)"),
    (dict(start="2026-10-12T20:00:00+09:00"), "10/12(월) 20:00"),
    (dict(start="2026-10-12T20:00:00+09:00", time="무시되는 시간"), "10/12(월) 20:00"),  # start에 시각이 있으면 time 필드는 붙이지 않는다
    (dict(start="2026-10-12T20:00:00+09:00", end="2026-10-12T22:00:00+09:00"), "10/12(월) 20:00 ~ 22:00"),
    (dict(start="2026-10-12T20:00:00+09:00", end="2026-10-13T01:00:00+09:00"), "10/12(월) 20:00 ~ 10/13(화) 01:00"),
    (dict(start="2026-10-12", place="홍대"), "10/12(월) · 홍대"),
])
def test_describe_event(ev, text):
    assert alerts.describe_event({"kind": "popup", "title": "t", **ev}) == text


def test_events_are_ordered_by_start_soonest_first():
    a = got(event(start="2026-10-30", source="sl-1"), event(start="2026-10-12T20:00:00+09:00", source="sl-1"), event(start="2026-10-20"))
    assert [x["description"].split(" ")[0] for x in a] == ["10/12(월)", "10/20(화)", "10/30(금)"]


# ---------------------------------------------------------------- 다른 알림과의 순서·상한
def live_member():
    return {"lize": {"live": {"on": True, "title": "방송", "url": "https://chzzk.naver.com/live/x", "since": "2026-10-09T12:40:00+09:00"}}}


def test_order_is_live_notice_event_music_video():
    fresh = [
        {"id": "yt-v", "date": "2026-10-09T12:00:00+09:00", "cat": "영상", "who": ["lize"], "title": "영상", "url": "u", "yt": "v"},
        {"id": "mu-1", "date": "2026-10-09", "cat": "음악", "who": ["lize"], "title": "곡", "url": "u"},
        {"id": "sl-9", "date": "2026-10-09", "cat": "공지", "who": ["all"], "title": "공지", "url": "u"},
    ]
    out = alerts.build_alerts(fresh, {}, live_member(), NOW, fresh_events=[event()], news_items=NEWS)
    assert [a["kind"] for a in out] == ["live", "notice", "event", "music", "video"]
    assert list(alerts.KIND_ORDER) == ["live", "notice", "event", "music", "video"]


def test_build_alerts_without_events_works_as_before():
    assert alerts.build_alerts([], {}, {}, NOW) == []


def test_events_survive_the_twenty_item_cap_that_cuts_videos_first():
    videos = [{"id": f"yt-{i}", "date": "2026-10-09T12:00:00+09:00", "cat": "영상", "who": ["lize"], "title": f"v{i}", "url": "u", "yt": f"v{i}"} for i in range(25)]
    todo = alerts.build_alerts(videos, {}, {}, NOW, fresh_events=[event()], news_items=NEWS)
    messages = discord.build_messages(todo, {"members": {}, "groups": []}, site_url="https://x/")
    shown = [e for m in messages for e in m["embeds"]]
    assert len(shown) == 20 and "일정 추가" in shown[0]["author"]["name"] and messages[-1]["content"].startswith("외 6건")


# ---------------------------------------------------------------- 임베드
def test_embed_has_the_label_title_notice_link_description_and_no_thumbnail_or_timestamp(members):
    (a,) = got(event(end="2026-11-01", time="10:00–20:00", place="서울 광진구 광나루로 441", who=["lize"]))
    e = discord.build_embed(a, members)
    assert e["author"]["name"] == "아카네 리제 · 📅 일정 추가"
    assert e["title"] == "STELLA MODE:ON 팝업스토어" and e["url"] == "https://stellive.me/news/1"
    assert e["description"] == "10/23(금) ~ 11/1(일) · 10:00–20:00 · 서울 광진구 광나루로 441"
    assert "thumbnail" not in e and "timestamp" not in e
    assert e["color"] == int(members["members"]["lize"]["c"][1:], 16)


def test_embed_for_an_all_event_uses_the_group_label_and_default_color(members):
    (a,) = got(event())
    e = discord.build_embed(a, members)
    assert e["author"]["name"] == "스텔라이브 · 📅 일정 추가" and e["color"] == config.DISCORD_DEFAULT_COLOR


def test_other_alert_kinds_have_no_description_key(members):
    e = discord.build_embed({"kind": "notice", "cat": "공지", "who": ["all"], "title": "t", "url": "u", "date": "2026-10-09", "yt": None}, members)
    assert "description" not in e


def test_description_is_clipped_to_the_discord_limit(members):
    a = {"kind": "event", "cat": "일정", "who": ["all"], "title": "t", "url": "u", "date": None, "yt": None, "description": "가" * 5000}
    assert len(discord.build_embed(a, members)["description"]) == 4096


def test_dry_run_output_shows_the_description(members):
    (a,) = got(event(place="서울"))
    text = discord.format_dry_run(discord.build_messages([a], members, site_url="https://x/"))
    assert "일정 추가" in text and "설명: 10/23(금) · 서울" in text
