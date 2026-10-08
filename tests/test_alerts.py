"""알림 대상 판정 규칙 (SPEC 7장 + 방송 시작 since 규칙). 순수 함수라 가짜 시계만 있으면 된다."""
from datetime import timedelta

import pytest

from updater import alerts, config, timeutil

NOW = timeutil.parse_kst("2026-10-06T12:00:00+09:00")


def iso(delta: timedelta) -> str:
    """NOW 기준 상대 시각 → +09:00 ISO."""
    return timeutil.to_kst_iso(NOW + delta)


def hours(h=0, m=0, s=0):
    return timedelta(hours=h, minutes=m, seconds=s)


def item(id_, date, **kw):
    base = {"id": id_, "date": date, "cat": "영상", "who": ["lize"], "title": "제목", "url": "https://example.invalid/x"}
    return {**base, **kw}


# ============================ 영상 (6시간) =====================================
@pytest.mark.parametrize("age, expected", [
    (hours(0, 1), True),
    (hours(5, 59, 59), True),
    (hours(6), True),            # 정확히 6시간은 이내
    (hours(6, 0, 1), False),
    (hours(30), False),
    (-hours(2), True),           # 미래 날짜(예정 프리미어)도 새로 보였으니 알린다
])
def test_video_window(age, expected):
    got = alerts.news_alerts([item("yt-a", iso(-age))], NOW)
    assert bool(got) is expected


def test_the_video_window_is_configurable_in_one_place():
    assert config.ALERT_VIDEO_HOURS == 6


# ============================ 공지·새 곡 (달력 2일) ============================
@pytest.mark.parametrize("prefix, cat", [("sl", "공지"), ("mu", "음악")])
@pytest.mark.parametrize("days_ago, expected", [(0, True), (1, True), (2, True), (3, False), (40, False), (-1, True)])
def test_notice_and_music_use_calendar_days(prefix, cat, days_ago, expected):
    date = (NOW - timedelta(days=days_ago)).date().isoformat()  # 날짜만 있는 값
    assert bool(alerts.news_alerts([item(f"{prefix}-1", date, cat=cat)], NOW)) is expected


def test_calendar_days_do_not_depend_on_the_time_of_day():
    late_night = timeutil.parse_kst("2026-10-06T00:05:00+09:00")
    assert alerts.news_alerts([item("sl-1", "2026-10-04", cat="공지")], late_night)      # 10-04 → 이틀 전
    assert not alerts.news_alerts([item("sl-1", "2026-10-03", cat="공지")], late_night)  # 사흘 전 (시각이 몇 시든 날짜로 센다)
    just_before_midnight = timeutil.parse_kst("2026-10-05T23:59:00+09:00")
    assert alerts.news_alerts([item("sl-1", "2026-10-03", cat="공지")], just_before_midnight)


def test_utc_now_is_converted_to_kst_dates():
    now_utc = timeutil.parse_kst("2026-10-05T16:00:00+00:00")  # = 10-06 01:00 KST
    assert alerts.news_alerts([item("sl-1", "2026-10-04", cat="공지")], now_utc)
    assert not alerts.news_alerts([item("sl-1", "2026-10-03", cat="공지")], now_utc)


# ============================ 공통 ===========================================
def test_unknown_id_kinds_are_never_alerted():
    assert alerts.news_alerts([item("zz-1", iso(-hours(1))), item("nope", iso(-hours(1)))], NOW) == []


@pytest.mark.parametrize("bad", [None, "", "어제", "2026-13-45"])
def test_unreadable_dates_are_skipped_with_a_warning(bad, caplog):
    with caplog.at_level("WARNING"):
        assert alerts.news_alerts([item("yt-a", bad), item("yt-b", iso(-hours(1)))], NOW) == [
            alerts.news_alerts([item("yt-b", iso(-hours(1)))], NOW)[0]
        ]
    assert "yt-a" in caplog.text


def test_item_without_a_date_key_is_skipped():
    broken = {"id": "yt-a", "who": ["lize"], "title": "x", "url": "u"}
    assert alerts.news_alerts([broken], NOW) == []


def test_alert_carries_what_the_embed_needs():
    (a,) = alerts.news_alerts([item("yt-a", iso(-hours(1)), who=["rin", "nana"], title="T", url="https://u", yt="VID")], NOW)
    assert a == {"kind": "video", "cat": "영상", "who": ["rin", "nana"], "title": "T", "url": "https://u", "date": iso(-hours(1)), "yt": "VID", "short": None}


def test_input_is_not_mutated():
    src = item("yt-a", iso(-hours(1)), who=["lize"])
    before = dict(src, who=list(src["who"]))
    alerts.news_alerts([src], NOW)[0]["who"].append("x")
    assert src == before


# ============================ 방송 시작 (since 규칙) ============================
def live(since=None, **kw):
    d = {"on": True, "title": "방송", "url": "https://chzzk.naver.com/live/x", "checkedAt": iso(-hours(0, 1))}
    if since is not None:
        d["since"] = since
    return {**d, **kw}


def off():
    return {"on": False, "checkedAt": iso(-hours(0, 30))}


def run(prev_live, new_live, key="lize"):
    prev = {} if prev_live is None else {key: {"live": prev_live}}
    return alerts.live_alerts(prev, {key: {"live": new_live}}, NOW)


S_NOW = lambda m: iso(-hours(0, m))  # m분 전에 시작한 방송


def test_new_broadcast_after_off_is_alerted():
    (a,) = run(off(), live(S_NOW(10)))
    assert a["kind"] == "live" and a["who"] == ["lize"] and a["title"] == "방송" and a["date"] == S_NOW(10)


def test_no_previous_entry_counts_as_off():
    assert len(run(None, live(S_NOW(10)))) == 1


def test_same_since_is_not_alerted_however_long_the_check_gap_was():
    same = S_NOW(30)
    stale_prev = live(same, checkedAt=iso(-hours(9)))      # 확인이 9시간 비어 있었어도
    assert run(stale_prev, live(same, checkedAt=iso(-hours(0, 1)))) == []
    assert run(live(same), live(same)) == []                 # 평소에도 당연히


def test_different_since_while_still_on_is_a_new_broadcast():
    (a,) = run(live(S_NOW(50)), live(S_NOW(5)))  # 이전 방송이 끝나고 새로 시작했다 (그 사이를 못 봄)
    assert a["date"] == S_NOW(5)


@pytest.mark.parametrize("minutes_ago, expected", [(0, True), (59, True), (60, True), (61, False), (180, False)])
def test_late_alert_guard_is_one_hour_from_since(minutes_ago, expected):
    assert bool(run(off(), live(S_NOW(minutes_ago)))) is expected


def test_one_second_over_the_hour_is_late():
    assert run(off(), live(iso(-hours(1, 0, 1)))) == []
    assert len(run(off(), live(iso(-hours(1))))) == 1


def test_late_guard_applies_to_a_changed_since_too():
    assert run(live(S_NOW(300)), live(S_NOW(90))) == []  # since가 달라졌어도 이미 90분 전에 시작한 방송이면 늦은 알림


def test_since_in_the_future_is_not_late():
    assert len(run(off(), live(iso(hours(0, 3))))) == 1  # 시계 오차


def test_same_instant_in_another_offset_is_the_same_broadcast():
    same_utc = timeutil.parse_kst(S_NOW(20)).astimezone(timeutil.parse_kst("2026-01-01T00:00:00+00:00").tzinfo).isoformat()
    assert same_utc != S_NOW(20) and run(live(S_NOW(20)), live(same_utc)) == []


def test_off_now_never_alerts():
    assert run(live(S_NOW(10)), off()) == [] and run(off(), off()) == [] and run(None, {"on": False}) == []


# --- since가 없을 때: 이전 규칙(꺼짐→켜짐) ---
@pytest.mark.parametrize("since", [None, "", "방금", "2026-99-99T00:00:00+09:00"])
def test_without_a_usable_since_only_off_to_on_alerts(since):
    new = live() if since is None else live(since)
    assert len(run(off(), new)) == 1       # 꺼짐 → 켜짐
    assert len(run(None, new)) == 1        # 이전 항목 없음 = 꺼짐
    assert run(live(), new) == []          # 켜짐 → 켜짐
    assert run(live(S_NOW(30)), new) == [] # 이전엔 since가 있었어도, 지금 없으면 이전 규칙 (켜져 있었으니 알리지 않음)


def test_without_since_a_long_check_gap_does_not_matter_either():
    assert run(live(checkedAt=iso(-hours(9))), live()) == []


def test_late_guard_needs_a_since_so_it_does_not_apply_without_one():
    assert len(run(off(), live())) == 1  # since가 없으면 얼마나 오래됐는지 알 수 없다 → 이전 규칙대로 알림


# --- 확인에 실패한 멤버: 새 status에도 이전 값이 그대로 있다 ---
def test_carried_over_previous_value_never_alerts():
    carried = live(S_NOW(20), checkedAt=iso(-hours(5)))
    assert run(carried, dict(carried)) == []
    carried_no_since = live(checkedAt=iso(-hours(5)))
    assert run(carried_no_since, dict(carried_no_since)) == []


def test_members_without_live_are_ignored_and_other_members_still_alert():
    prev = {"tabi": {"avatar": "A"}}
    new = {"tabi": {"avatar": "A"}, "lize": {"live": live(S_NOW(5))}, "rin": {}, "nana": None}
    assert [a["who"] for a in alerts.live_alerts(prev, new, NOW)] == [["lize"]]


def test_empty_title_is_kept_empty_so_the_embed_can_fill_it():
    assert run(off(), live(S_NOW(5), title=""))[0]["title"] == ""
    assert run(off(), live(S_NOW(5), title=None))[0]["title"] == ""


def test_inputs_are_not_mutated_by_live_alerts():
    prev, new = {"lize": {"live": off()}}, {"lize": {"live": live(S_NOW(5))}}
    import copy
    before = copy.deepcopy((prev, new))
    alerts.live_alerts(prev, new, NOW)
    assert (prev, new) == before


# ============================ 합치기·정렬 =====================================
def test_build_alerts_orders_live_notice_music_video_newest_first():
    fresh = [
        item("yt-old", iso(-hours(5))), item("yt-new", iso(-hours(1))),
        item("sl-1", "2026-10-05", cat="공지"), item("sl-2", "2026-10-06", cat="굿즈"),
        item("mu-1", "2026-10-06", cat="음악"),
    ]
    got = alerts.build_alerts(fresh, {}, {"lize": {"live": live(S_NOW(5))}}, NOW)
    assert [(a["kind"], a["title"]) for a in got][:1] == [("live", "방송")]
    assert [a["kind"] for a in got] == ["live", "notice", "notice", "music", "video", "video"]
    assert [a["date"] for a in got if a["kind"] == "notice"] == ["2026-10-06", "2026-10-05"]  # 최신순
    assert [a["date"] for a in got if a["kind"] == "video"] == [iso(-hours(1)), iso(-hours(5))]


def test_build_alerts_with_nothing_new_is_empty():
    assert alerts.build_alerts([], {}, {}, NOW) == []
