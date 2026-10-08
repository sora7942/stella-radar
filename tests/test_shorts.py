"""쇼츠 판별(updater/shorts.py) — 가짜 YouTube API(fakeapi.FakeApi), 네트워크 없음.
약속: ① UUSH에 있으면 true, UULF에 있으면 false, 둘 다 없으면 필드 없이 재시도 ② added 24시간 뒤에는 false로 확정 ③ 한 번 정해진 값은 불변
④ 조회 실패면 그 조회에 기대는 항목은 하나도 안 바뀐다 ⑤ 채널마다 목록 호출은 실행당 최대 1회 ⑥ 키는 헤더로만, 어디에도 안 남는다."""
import collections
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from conftest import make_response
from fakeapi import KANGJI, KEY, LIZE, OFFICIAL, FakeApi, http_error
from updater import config, shorts
from updater.sources.youtube_rss import Channel

KST = config.KST
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=KST)
CH_LIZE = Channel(LIZE, "아카네 리제 유튜브", "lize")
CH_KANGJI = Channel(KANGJI, "강지 유튜브", "kangji")
CH_OFFICIAL = Channel(OFFICIAL, "스텔라이브 공식 유튜브", None)
CHANNELS = [CH_KANGJI, CH_LIZE, CH_OFFICIAL]
SH = lambda cid: config.SHORTS_PLAYLIST_PREFIX + cid[2:]  # noqa: E731
LF = lambda cid: config.LONG_PLAYLIST_PREFIX + cid[2:]  # noqa: E731


def iso(dt):
    return dt.isoformat(timespec="seconds")


def item(vid, ch=CH_LIZE, *, age=timedelta(hours=1), **extra):
    """news 항목. age = 처음 발견(added)한 지 얼마나 됐는가."""
    return {"id": f"yt-{vid}", "date": iso(NOW - age), "added": iso(NOW - age), "cat": "영상", "who": [ch.owner or "all"], "title": f"영상 {vid}",
            "url": f"https://www.youtube.com/watch?v={vid}", "source": ch.source, "yt": vid, **extra}


def playlist(*vids):
    return {"kind": "youtube#playlistItemListResponse", "items": [{"contentDetails": {"videoId": v}} for v in vids]}


def api(*, shorts_of=None, longs_of=None, **kw):
    """shorts_of / longs_of = {채널 ID: [videoId…]} → 해당 UUSH / UULF 목록. 지정하지 않은 목록은 빈 목록(200)."""
    pls = {SH(c): playlist(*v) for c, v in (shorts_of or {}).items()}
    pls.update({LF(c): playlist(*v) for c, v in (longs_of or {}).items()})
    return FakeApi(playlists=pls, **kw)


def run(items, fake, channels=CHANNELS, now=NOW):
    return shorts.fill(items, channels, api_key=KEY, now=now, get=fake)


def playlist_ids(fake):
    return [parse_qs(urlparse(u).query)["playlistId"][0] for u, _ in fake.calls]


# ============================ 대상 선정 ======================================
def test_only_yt_items_without_a_short_field_are_pending():
    ok = item("A")
    assert shorts.is_pending(ok)
    assert not shorts.is_pending(item("B", short=True)) and not shorts.is_pending(item("C", short=False))  # 정해진 값은 대상이 아니다
    assert not shorts.is_pending({**item("D"), "id": "mu-123"})  # 음악: 채널을 알 수 없어 제외
    assert not shorts.is_pending({**item("E"), "id": "sl-14044", "yt": None})
    assert not shorts.is_pending({**item("F"), "yt": None}) and not shorts.is_pending({k: v for k, v in item("G").items() if k != "yt"})


def test_nothing_pending_means_zero_api_calls():
    fake = api()
    rep = run([item("A", short=True), item("B", short=False), {**item("C"), "id": "mu-1"}], fake)
    assert fake.calls == [] and (rep.pending, rep.calls, rep.channels, rep.undecided) == (0, 0, 0, 0)


# ============================ 값 정하기 ======================================
def test_in_the_shorts_list_becomes_true():
    items = [item("S1")]
    rep = run(items, api(shorts_of={LIZE: ["S1"]}))
    assert items[0]["short"] is True and (rep.short, rep.long, rep.undecided) == (1, 0, 0)


def test_in_the_long_list_becomes_false():
    items = [item("L1")]
    rep = run(items, api(longs_of={LIZE: ["L1"]}))
    assert items[0]["short"] is False and (rep.short, rep.long, rep.confirmed_long, rep.undecided) == (0, 1, 0, 0)


def test_in_both_lists_the_shorts_tab_wins():
    items = [item("X"), item("N1")]  # N1이 목록에 없어 UULF도 불리고, 그 목록에도 X가 들어 있다
    fake = api(shorts_of={LIZE: ["X"]}, longs_of={LIZE: ["X"]})
    run(items, fake)
    assert LF(LIZE) in playlist_ids(fake) and items[0]["short"] is True and "short" not in items[1]


def test_in_neither_list_the_field_is_not_created_and_it_is_retried_next_run():
    items = [item("N1", age=timedelta(hours=2))]
    rep = run(items, api())
    assert "short" not in items[0] and rep.undecided == 1 and rep.short == rep.long == rep.confirmed_long == 0
    # 다음 실행: 이제 UUSH 목록에 나타났다
    rep2 = run(items, api(shorts_of={LIZE: ["N1"]}), now=NOW + timedelta(minutes=30))
    assert items[0]["short"] is True and rep2.pending == 1 and rep2.short == 1


def test_undecided_items_do_not_block_decided_ones_in_the_same_channel():
    items = [item("S1"), item("L1"), item("N1")]
    run(items, api(shorts_of={LIZE: ["S1"]}, longs_of={LIZE: ["L1"]}))
    assert items[0]["short"] is True and items[1]["short"] is False and "short" not in items[2]


# ============================ 24시간 확정 ====================================
@pytest.mark.parametrize("age, decided", [
    (timedelta(hours=23, minutes=59, seconds=59), False),
    (timedelta(hours=24), True),
    (timedelta(hours=25), True),
    (timedelta(hours=24 * 30), True),  # 백필: 오래전에 발견된 영상도 같은 규칙
    (timedelta(minutes=5), False),
])
def test_after_24_hours_in_neither_list_it_is_confirmed_false(age, decided):
    items = [item("N1", age=age)]
    rep = run(items, api())
    if decided:
        assert items[0]["short"] is False and rep.confirmed_long == 1 and rep.undecided == 0
    else:
        assert "short" not in items[0] and rep.confirmed_long == 0 and rep.undecided == 1


def test_confirmation_uses_added_not_the_publish_date():
    old_video_new_to_us = {**item("N1", age=timedelta(hours=1)), "date": iso(NOW - timedelta(days=30))}  # 오래된 영상이지만 방금 처음 봤다
    run([old_video_new_to_us], api())
    assert "short" not in old_video_new_to_us


def test_the_confirmation_hours_come_from_config():
    assert config.SHORTS_CONFIRM_HOURS == 24


def test_an_unreadable_added_never_confirms():
    bad = {**item("N1"), "added": "어제"}
    missing = {k: v for k, v in item("N2").items() if k != "added"}
    run([bad, missing], api())
    assert "short" not in bad and "short" not in missing


def test_a_found_video_is_decided_by_the_lists_even_if_young():
    items = [item("S1", age=timedelta(seconds=1))]
    run(items, api(shorts_of={LIZE: ["S1"]}))
    assert items[0]["short"] is True


# ============================ 한 번 정해진 값은 바뀌지 않는다 ======================
def test_existing_values_are_never_changed_even_if_the_lists_disagree():
    was_true, was_false = item("A", short=True), item("B", short=False)
    pending = item("C")
    fake = api(shorts_of={LIZE: ["B", "C"]}, longs_of={LIZE: ["A"]})  # 목록은 A·B가 반대라고 말한다
    run([was_true, was_false, pending], fake)
    assert was_true["short"] is True and was_false["short"] is False and pending["short"] is True
    assert set(playlist_ids(fake)) == {SH(LIZE)}  # 정해진 항목 때문에 목록을 더 부르지도 않는다 (C가 UUSH에서 확인돼 UULF는 건너뜀)


def test_running_twice_changes_nothing_the_second_time():
    items = [item("S1"), item("L1"), item("N1", age=timedelta(hours=30))]
    fake = api(shorts_of={LIZE: ["S1"]}, longs_of={LIZE: ["L1"]})
    run(items, fake)
    snapshot = json.dumps(items, ensure_ascii=False, sort_keys=True)
    fake2 = api()
    rep = run(items, fake2, now=NOW + timedelta(hours=1))
    assert json.dumps(items, ensure_ascii=False, sort_keys=True) == snapshot and fake2.calls == [] and rep.pending == 0


# ============================ 조회 실패 ======================================
def test_a_failed_shorts_lookup_changes_nothing_for_that_channel_and_retries_next_run():
    items = [item("S1"), item("N1", age=timedelta(hours=30))]  # 정상이었다면 true와 24시간 확정 false가 됐을 항목들
    rep = run(items, api(shorts_of={LIZE: ["S1"]}, fail={("playlistItems", SH(LIZE)): http_error(500, b"<html>oops</html>")}))
    assert all("short" not in it for it in items) and rep.failed_channels == 1 and rep.undecided == 2
    run(items, api(shorts_of={LIZE: ["S1"]}), now=NOW + timedelta(minutes=30))  # 다음 실행에서 복구
    assert items[0]["short"] is True and items[1]["short"] is False


def test_a_failed_long_lookup_changes_nothing_either_even_for_items_found_in_shorts():
    items = [item("S1"), item("N1")]  # N1이 목록에 없어 UULF가 필요하고, 그 조회가 실패한다
    rep = run(items, api(shorts_of={LIZE: ["S1"]}, fail={("playlistItems", LF(LIZE)): http_error(503, b"x")}))
    assert all("short" not in it for it in items) and rep.failed_channels == 1  # 채널 단위로 전부-아니면-전무
    assert [it for it in items if "short" in it] == []


def test_a_channel_failure_does_not_block_other_channels():
    items = [item("S1", CH_LIZE), item("S2", CH_KANGJI)]
    rep = run(items, api(shorts_of={LIZE: ["S1"], KANGJI: ["S2"]}, fail={("playlistItems", SH(LIZE)): requests.ConnectionError("down")}))
    assert "short" not in items[0] and items[1]["short"] is True and rep.failed_channels == 1 and rep.channels == 2


@pytest.mark.parametrize("fake_kw, reason", [
    ({"quota_after": 0}, "HTTP 403 quotaExceeded"),
    ({"reject_after": 0}, "HTTP 403 forbidden"),  # 키 없음/거부
])
def test_quota_or_key_rejection_stops_everything_and_changes_nothing(fake_kw, reason):
    items = [item("S1", CH_LIZE), item("S2", CH_KANGJI), item("N3", CH_OFFICIAL, age=timedelta(hours=30))]
    fake = api(shorts_of={LIZE: ["S1"], KANGJI: ["S2"]}, **fake_kw)
    rep = run(items, fake)
    assert all("short" not in it for it in items) and rep.aborted == reason and rep.undecided == 3
    assert len(fake.calls) == 1  # 첫 호출에서 멈춘다 — 남은 채널은 부르지 않는다
    assert reason in rep.summary()


def test_quota_in_the_middle_keeps_finished_channels_and_skips_the_rest():
    items = [item("S1", CH_LIZE), item("S2", CH_KANGJI)]
    fake = api(shorts_of={LIZE: ["S1"], KANGJI: ["S2"]}, quota_after=1)  # 첫 채널의 UUSH(전부 쇼츠라 UULF 없음)까지만 성공
    rep = run(items, fake)
    assert items[0]["short"] is True and "short" not in items[1] and rep.aborted and rep.undecided == 1


def test_a_missing_playlist_404_counts_as_an_empty_tab():
    items = [item("L1")]
    rep = run(items, api(longs_of={LIZE: ["L1"]}, stale={SH(LIZE)}))  # 쇼츠 탭 재생목록이 없는 채널
    assert items[0]["short"] is False and rep.failed_channels == 0


def test_both_tabs_missing_just_leaves_it_to_the_24_hour_rule():
    young, old = item("Y", age=timedelta(hours=1)), item("O", age=timedelta(hours=25))
    run([young, old], api(stale={SH(LIZE), LF(LIZE)}))
    assert "short" not in young and old["short"] is False


# ============================ 호출 횟수 ======================================
def test_each_list_is_requested_at_most_once_per_channel_per_run():
    items = [item(f"V{i}", CH_LIZE) for i in range(20)] + [item(f"K{i}", CH_KANGJI) for i in range(20)] + [item("O1", CH_OFFICIAL)]
    fake = api()
    rep = run(items, fake)
    counts = collections.Counter(playlist_ids(fake))
    assert set(counts.values()) == {1} and len(counts) == rep.calls == 6  # 3채널 × (UUSH + UULF), 영상이 41개여도 6회
    assert rep.channels == 3


def test_uulf_is_skipped_when_everything_is_already_found_in_shorts():
    items = [item("S1", CH_LIZE), item("S2", CH_LIZE), item("N1", CH_KANGJI)]
    fake = api(shorts_of={LIZE: ["S1", "S2"]})
    rep = run(items, fake)
    assert playlist_ids(fake) == [SH(LIZE), SH(KANGJI), LF(KANGJI)] and rep.calls == 3


def test_only_channels_with_pending_items_are_called():
    items = [item("A", CH_LIZE, short=True), item("B", CH_KANGJI)]
    fake = api(longs_of={KANGJI: ["B"]})
    run(items, fake)
    assert {SH(KANGJI), LF(KANGJI)} == set(playlist_ids(fake)) and not any(LIZE[2:] in p for p in playlist_ids(fake))


def test_twelve_channels_cost_at_most_24_calls():
    channels = [Channel("UC" + f"{n:022d}", f"채널{n}", None) for n in range(12)]
    items = [item(f"V{n}", ch) for n, ch in enumerate(channels)]
    fake = api()
    rep = run(items, fake, channels=channels)
    assert rep.calls == len(fake.calls) == 24 and set(collections.Counter(playlist_ids(fake)).values()) == {1}


def test_items_whose_channel_is_unknown_are_skipped_without_a_call():
    items = [item("A", Channel("UCzzzzzzzzzzzzzzzzzzzzzz", "모르는 채널", None))]
    fake = api()
    rep = run(items, fake)
    assert fake.calls == [] and rep.unmatched == 1 and rep.undecided == 1 and "short" not in items[0]


# ============================ 요청 모양과 키 ===================================
def test_requests_go_to_the_two_tab_playlists_with_the_key_in_the_header_only():
    fake = api()
    run([item("N1")], fake)
    first = parse_qs(urlparse(fake.calls[0][0]).query)
    assert first["playlistId"] == ["UUSH" + LIZE[2:]] and first["maxResults"] == ["50"] and first["part"] == ["contentDetails"]
    assert parse_qs(urlparse(fake.calls[1][0]).query)["playlistId"] == ["UULF" + LIZE[2:]]
    assert set(fake.endpoints()) == {"playlistItems"}  # search.list·videos.list는 쓰지 않는다
    assert all(kw["headers"] == {"X-Goog-Api-Key": KEY} and KEY not in url for url, kw in fake.calls)


def test_playlist_ids_follow_the_uc_to_uu_convention():
    assert shorts.config.SHORTS_PLAYLIST_PREFIX == "UUSH" and shorts.config.LONG_PLAYLIST_PREFIX == "UULF"
    assert SH(LIZE) == "UUSH" + LIZE[2:] and LIZE.startswith("UC")


def test_the_key_never_leaks_through_logs_errors_or_the_report(caplog):
    leaky = requests.ConnectionError(f"boom https://x/?key={KEY}")
    for fake in (api(fail={("playlistItems", SH(LIZE)): leaky}), api(quota_after=0), api(reject_after=0),
                 api(fail={("playlistItems", SH(LIZE)): http_error(500, b"{}")})):
        with caplog.at_level(logging.DEBUG):
            rep = run([item("N1")], fake)
        assert KEY not in caplog.text and KEY not in rep.summary()


def test_an_unexpected_error_is_not_swallowed_here():
    class Boom:
        def __call__(self, url, **kw):
            raise RuntimeError("코드 결함")

    with pytest.raises(RuntimeError):
        shorts.fill([item("N1")], CHANNELS, api_key=KEY, now=NOW, get=Boom())  # 예상 밖 오류는 올라간다 — main.py가 경고만 남기고 계속한다


def test_summary_text():
    items = [item("S1"), item("L1"), item("N1"), item("O1", age=timedelta(hours=30))]
    text = run(items, api(shorts_of={LIZE: ["S1"]}, longs_of={LIZE: ["L1"]})).summary()
    assert text == "쇼츠 판별: 대상 4개 → 쇼츠 1 · 일반 2(24시간 확정 1) · 미정 1 · 조회 채널 1개, API 2회"


def test_items_are_modified_in_place_and_other_fields_untouched():
    it = item("S1")
    before = dict(it)
    run([it], api(shorts_of={LIZE: ["S1"]}))
    assert {k: v for k, v in it.items() if k != "short"} == before and list(it)[-1] == "short"
