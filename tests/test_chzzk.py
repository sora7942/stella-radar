"""치지직 live-status 파서·수집. 전부 픽스처·가짜 응답 (네트워크 없음).
chzzk_live_open.json은 닫힌 응답에서 필드만 바꾼 **합성**이다 (tests/fixtures/README.md)."""
import json

import pytest
import requests

from conftest import FIXTURES, make_response
from updater import config
from updater.sources import chzzk

LIZE_ID = "4325b1d5bbc321fad3042306646e2e50"  # 두 픽스처의 channelId


def doc(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ============================ 파서 ============================================
def test_closed_channel_is_off_even_though_content_is_filled():
    assert chzzk.parse_live(doc("chzzk_live_close.json"), LIZE_ID) == {"on": False}


def test_open_channel_has_title_url_and_since_in_kst():
    live = chzzk.parse_live(doc("chzzk_live_open.json"), LIZE_ID)
    assert live == {
        "on": True,
        "title": "합성 방송 제목 (테스트용)",
        "url": f"https://chzzk.naver.com/live/{LIZE_ID}",
        "since": "2026-10-06T20:30:10+09:00",  # 오프셋 없는 KST 문자열에 +09:00을 붙인다
    }
    assert list(live) == ["on", "title", "url", "since"]


def test_title_is_stripped_and_missing_title_becomes_empty():
    d = doc("chzzk_live_open.json")
    d["content"]["liveTitle"] = "  제목  "
    assert chzzk.parse_live(d, LIZE_ID)["title"] == "제목"
    d["content"]["liveTitle"] = None
    assert chzzk.parse_live(d, LIZE_ID)["title"] == ""


def test_unreadable_open_date_keeps_the_live_state_without_since(caplog):
    for bad in (None, "어제 저녁", "2026-10-06T20:30:10+09:00"):
        d = doc("chzzk_live_open.json")
        d["content"]["openDate"] = bad
        with caplog.at_level("WARNING"):
            live = chzzk.parse_live(d, LIZE_ID)
        assert live["on"] is True and "since" not in live
    assert "openDate" in caplog.text


def test_open_date_missing_key():
    d = doc("chzzk_live_open.json")
    del d["content"]["openDate"]
    assert "since" not in chzzk.parse_live(d, LIZE_ID)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(code=404),
    lambda d: d.update(content=None),
    lambda d: d.update(content="x"),
    lambda d: d["content"].update(status=None),
    lambda d: d["content"].pop("status"),
    lambda d: d["content"].update(channelId="someoneelse"),
])
def test_unexpected_shapes_are_errors_not_off(mutate):
    d = doc("chzzk_live_close.json")
    mutate(d)
    with pytest.raises(chzzk.LiveParseError):
        chzzk.parse_live(d, LIZE_ID)


@pytest.mark.parametrize("not_a_dict", [None, [], "<html>blocked</html>", 7])
def test_non_object_responses_are_errors(not_a_dict):
    with pytest.raises(chzzk.LiveParseError):
        chzzk.parse_live(not_a_dict, LIZE_ID)


def test_missing_channel_id_in_response_is_tolerated():
    d = doc("chzzk_live_close.json")
    del d["content"]["channelId"]
    assert chzzk.parse_live(d, LIZE_ID) == {"on": False}


# ============================ collect ========================================
MEMBERS = {
    "kangji": {"n": "강지", "chzzk_id": None},  # 아직 모름 → 요청하지 않는다
    "lize": {"n": "아카네 리제", "chzzk_id": "ID_LIZE"},
    "tabi": {"n": "아라하시 타비", "chzzk_id": "ID_TABI"},
    "rin": {"n": "아오쿠모 린"},                  # 키 자체가 없어도 건너뛴다
}


def getter(*, open_ids=(), fail=None, bad_body=None):
    calls = []

    def get(url, **kw):
        calls.append(url)
        cid = url.split("/channels/")[1].split("/")[0]
        if fail and cid in fail:
            raise fail[cid]
        if bad_body and cid in bad_body:
            return make_response(200, bad_body[cid])
        d = doc("chzzk_live_open.json" if cid in open_ids else "chzzk_live_close.json")
        d["content"]["channelId"] = cid
        return make_response(200, json.dumps(d))

    get.calls = calls
    return get


NOW_ISO = "2026-10-06T10:00:00+09:00"


def run(get, sleeps=None):
    return chzzk.collect(MEMBERS, now_iso=NOW_ISO, get=get, sleep=(sleeps if sleeps is not None else []).append)


def test_only_members_with_an_id_are_requested():
    get = getter(open_ids={"ID_TABI"})
    patches, errors = run(get)
    assert errors == []
    assert patches["lize"] == {"live": {"on": False, "checkedAt": NOW_ISO}}  # 꺼짐에도 확인 시각이 붙는다
    assert patches["tabi"]["live"]["on"] is True and patches["tabi"]["live"]["url"] == config.CHZZK_LIVE_PAGE_URL.format(channel_id="ID_TABI")
    assert list(patches["tabi"]["live"]) == ["on", "title", "url", "since", "checkedAt"] and patches["tabi"]["live"]["checkedAt"] == NOW_ISO
    assert set(patches) == {"lize", "tabi"}  # kangji·rin은 결과에 없다 (live 키를 만들어 내지 않는다)
    assert get.calls == [config.CHZZK_LIVE_STATUS_URL.format(channel_id=i) for i in ("ID_LIZE", "ID_TABI")]


def test_pauses_between_requests_but_not_before_the_first():
    sleeps = []
    run(getter(), sleeps)
    assert sleeps == [config.REQUEST_DELAY]  # 2번 요청 → 사이 1번


def test_a_failed_member_has_no_live_patch_so_its_previous_value_survives():
    patches, errors = run(getter(fail={"ID_LIZE": requests.ConnectionError("blocked")}))
    assert "live" not in patches["lize"] and patches["lize"] == {"liveFails": 1}  # 실패를 {"on": False}로 쓰지 않는다. 연속 실패만 센다
    assert "live" in patches["tabi"]
    assert len(errors) == 1 and "아카네 리제" in errors[0]


def test_http_error_and_bad_json_and_wrong_channel_are_failures():
    resp403 = make_response(403)
    get = getter(
        fail={"ID_LIZE": requests.HTTPError("403", response=resp403)},
        bad_body={"ID_TABI": b"<html>not json</html>"},
    )
    patches, errors = run(get)
    assert patches == {"lize": {"liveFails": 1}, "tabi": {"liveFails": 1}} and len(errors) == 2

    def other_channel(url, **kw):
        d = doc("chzzk_live_close.json")
        d["content"]["channelId"] = "ZZZ"
        return make_response(200, json.dumps(d))

    patches, errors = chzzk.collect(MEMBERS, now_iso=NOW_ISO, get=other_channel, sleep=lambda s: None)
    assert all("live" not in p for p in patches.values()) and len(errors) == 2


# ============================ 5xx 재시도 =======================================
def http_error(status):
    return requests.HTTPError(f"{status} for url", response=make_response(status))


def scripted(per_id):
    """채널 ID별로 정해 둔 결과를 차례로 돌려주는 get. 결과: 'ok' | 'open' | 예외. 소진되면 마지막 결과를 반복한다."""
    calls = []
    queues = {cid: list(outs) for cid, outs in per_id.items()}

    def get(url, **kw):
        calls.append(url)
        cid = url.split("/channels/")[1].split("/")[0]
        outs = queues.get(cid, ["ok"])
        out = outs.pop(0) if len(outs) > 1 else outs[0]
        if isinstance(out, Exception):
            raise out
        d = doc("chzzk_live_open.json" if out == "open" else "chzzk_live_close.json")
        d["content"]["channelId"] = cid
        return make_response(200, json.dumps(d))

    get.calls = calls
    return get


V2, V3 = config.CHZZK_LIVE_STATUS_URLS


def urls_for(get, cid):
    return [u for u in get.calls if f"/channels/{cid}/" in u]


def test_the_endpoint_list_is_v2_first_then_v3_and_the_old_name_is_the_default():
    assert V2.endswith("/polling/v2/channels/{channel_id}/live-status") and V3.endswith("/polling/v3/channels/{channel_id}/live-status")
    assert config.CHZZK_LIVE_STATUS_URL == V2


def test_a_5xx_on_v2_falls_back_to_v3_right_away_without_waiting():
    get = scripted({"ID_LIZE": [http_error(500), "open"]})  # v2는 500, 같은 멤버의 다음 요청(v3)은 정상
    sleeps = []
    patches, errors = run(get, sleeps)
    assert errors == [] and patches["lize"]["live"]["on"] is True and "liveFails" not in patches["lize"]
    assert urls_for(get, "ID_LIZE") == [V2.format(channel_id="ID_LIZE"), V3.format(channel_id="ID_LIZE")]  # v2 → v3, 이 순서로 딱 2번
    assert urls_for(get, "ID_TABI") == [V2.format(channel_id="ID_TABI")]  # 정상 멤버는 v2 한 번뿐이다
    assert sleeps == [config.REQUEST_DELAY]  # 재시도 대기(1초) 없이 멤버 사이 0.5초만


def test_the_geo_blocked_member_is_read_from_v3_with_the_same_parser():
    """후야 사례: v2는 HTTP 500 code 9004(해외 시청 불가), v3는 200. 같은 파서로 방송 중 상태가 나온다."""
    blocked = requests.HTTPError("500", response=make_response(500, json.dumps({"code": 9004, "message": "해외 시청 불가능한 컨텐츠 입니다.", "content": None})))
    get = scripted({"ID_LIZE": [blocked, "open"]})
    patches, errors = run(get)
    assert errors == [] and patches["lize"]["live"] == {
        "on": True, "title": "합성 방송 제목 (테스트용)", "url": config.CHZZK_LIVE_PAGE_URL.format(channel_id="ID_LIZE"),
        "since": "2026-10-06T20:30:10+09:00", "checkedAt": NOW_ISO,
    }


def test_the_real_v3_closed_response_parses_like_the_v2_one():
    v3, v2 = doc("chzzk_live_v3_close.json"), doc("chzzk_live_close.json")
    assert set(v3["content"]) == set(v2["content"])  # 키 51개가 같다 (그래서 같은 파서를 쓴다)
    assert chzzk.parse_live(v3, LIZE_ID) == {"on": False}


def test_a_5xx_that_persists_on_every_endpoint_fails_after_one_more_round():
    get = scripted({"ID_LIZE": [http_error(500)]})  # v2·v3 모두 계속 500
    sleeps = []
    patches, errors = run(get, sleeps)
    lize = [V2, V3, V2, V3]
    assert urls_for(get, "ID_LIZE") == [u.format(channel_id="ID_LIZE") for u in lize]  # 한 바퀴 + 재시도 한 바퀴, 더 없다
    assert sleeps == [config.CHZZK_RETRY_DELAY, config.REQUEST_DELAY]  # 바퀴 사이 1초, 멤버 사이 0.5초
    assert patches["lize"] == {"liveFails": 1} and len(errors) == 1 and "아카네 리제" in errors[0]
    assert "live" in patches["tabi"]  # 다른 멤버는 영향 없다


@pytest.mark.parametrize("status", [500, 502, 503, 599])
def test_every_5xx_status_moves_on_to_the_next_endpoint(status):
    get = scripted({"ID_LIZE": [http_error(status), "ok"]})
    patches, errors = run(get)
    assert errors == [] and "live" in patches["lize"] and len(urls_for(get, "ID_LIZE")) == 2


@pytest.mark.parametrize("failure", [
    http_error(403), http_error(404), http_error(429),
    requests.ConnectionError("blocked"), requests.Timeout("slow"),
])
def test_4xx_and_connection_errors_are_not_retried_and_do_not_try_the_next_endpoint(failure):
    get = scripted({"ID_LIZE": [failure, "ok"]})  # 두 번째 결과가 'ok'여도 재시도·대체하지 않으니 못 본다
    sleeps = []
    patches, errors = run(get, sleeps)
    assert urls_for(get, "ID_LIZE") == [V2.format(channel_id="ID_LIZE")]
    assert patches["lize"] == {"liveFails": 1} and len(errors) == 1
    assert sleeps == [config.REQUEST_DELAY]  # 재시도 대기 없이 멤버 사이 간격만


def test_a_200_with_a_broken_body_is_not_retried_and_does_not_try_the_next_endpoint():
    get = getter(bad_body={"ID_LIZE": b"<html>blocked</html>"})
    patches, errors = run(get)
    assert urls_for(get, "ID_LIZE") == [V2.format(channel_id="ID_LIZE")] and patches["lize"] == {"liveFails": 1}


def test_the_extra_round_can_be_turned_off_and_the_default_is_one():
    assert config.CHZZK_RETRY_5XX == 1 and config.CHZZK_RETRY_DELAY == 1.0
    get = scripted({"ID_LIZE": [http_error(500)]})
    sleeps = []
    patches, errors = chzzk.collect(MEMBERS, now_iso=NOW_ISO, get=get, sleep=sleeps.append, retries=0)
    assert patches["lize"] == {"liveFails": 1}
    assert urls_for(get, "ID_LIZE") == [V2.format(channel_id="ID_LIZE"), V3.format(channel_id="ID_LIZE")]  # 후보는 그래도 둘 다 본다
    assert config.CHZZK_RETRY_DELAY not in sleeps  # 재시도 바퀴가 없으니 1초 대기도 없다


def test_logs_say_which_status_and_code_but_never_the_url_or_the_message(caplog):
    body = json.dumps({"code": 9004, "message": "해외 시청 불가능한 컨텐츠 입니다."})
    get = scripted({"ID_LIZE": [requests.HTTPError("500 for url https://api.chzzk.naver.com/x", response=make_response(500, body)), "ok"]})
    with caplog.at_level("INFO"):
        run(get)
    lines = [r.getMessage() for r in caplog.records if "엔드포인트" in r.getMessage()]
    assert lines == ["치지직 아카네 리제: HTTP 500 (code 9004) — 다음 엔드포인트 시도"]
    assert "api.chzzk" not in caplog.text and "해외 시청" not in caplog.text


def test_the_round_retry_is_logged_without_the_url(caplog):
    with caplog.at_level("INFO"):
        run(scripted({"ID_LIZE": [http_error(500)]}))
    assert "치지직 아카네 리제: 모든 엔드포인트가 5xx — 재시도 1/1" in caplog.text and "api.chzzk" not in caplog.text


@pytest.mark.parametrize("body, expected", [
    (json.dumps({"code": 9004}), 9004), (b"", None), (b"<html>", None), (json.dumps({"code": "9004"}), None),
    (json.dumps({"code": True}), None), (json.dumps([9004]), None), (json.dumps({"message": "x"}), None),
])
def test_the_api_code_is_read_defensively(body, expected):
    assert chzzk._api_code(make_response(500, body)) == expected


# ============================ 연속 실패 횟수 · 경고 =============================
def run_with_prev(get, prev, on_streak=None):
    return chzzk.collect(MEMBERS, now_iso=NOW_ISO, prev_status=prev, on_streak=on_streak, get=get, sleep=lambda s: None)


def test_the_streak_counts_up_from_the_previous_value_and_warns_from_the_third():
    seen = []
    fail = {"ID_LIZE": [http_error(500)]}
    patches, _ = run_with_prev(scripted(fail), {"lize": {"liveFails": 1}}, lambda *a: seen.append(a))
    assert patches["lize"] == {"liveFails": 2} and seen == []  # 2회째까지는 조용하다
    patches, _ = run_with_prev(scripted(fail), {"lize": {"liveFails": 2}}, lambda *a: seen.append(a))
    assert patches["lize"] == {"liveFails": 3} and seen == [("아카네 리제", 3, "HTTP 500")]  # 이름·횟수·상태만 (URL 없음)
    patches, _ = run_with_prev(scripted(fail), {"lize": {"liveFails": 3}}, lambda *a: seen.append(a))
    assert patches["lize"] == {"liveFails": 4} and seen[-1] == ("아카네 리제", 4, "HTTP 500")  # 계속되는 동안 매번 알린다


def test_the_warning_threshold_is_three_runs():
    assert config.CHZZK_FAIL_WARN_STREAK == 3


def test_the_streak_reason_includes_the_chzzk_code_when_the_error_body_has_one():
    seen = []
    body = json.dumps({"code": 9004, "message": "해외 시청 불가능한 컨텐츠 입니다."})
    blocked = requests.HTTPError("500", response=make_response(500, body))
    run_with_prev(scripted({"ID_LIZE": [blocked]}), {"lize": {"liveFails": 2}}, lambda *a: seen.append(a))  # v2·v3 모두 막힌 경우
    assert seen == [("아카네 리제", 3, "HTTP 500, code 9004")]  # 메시지 문구는 사유에 넣지 않는다


def test_a_non_http_failure_reports_the_exception_type_as_the_reason():
    seen = []
    run_with_prev(scripted({"ID_LIZE": [requests.ConnectionError("blocked by host name.invalid")]}), {"lize": {"liveFails": 2}}, lambda *a: seen.append(a))
    assert seen == [("아카네 리제", 3, "ConnectionError")]  # 예외 메시지(호스트·URL이 들어갈 수 있음)는 사유에 넣지 않는다


def test_a_success_after_failures_resets_the_streak():
    patches, errors = run_with_prev(scripted({}), {"lize": {"liveFails": 2}, "tabi": {"liveFails": 1}})
    assert errors == []
    assert patches["lize"] == {"live": {"on": False, "checkedAt": NOW_ISO}, "liveFails": 0}  # 병합 때 필드가 지워진다
    assert patches["tabi"]["liveFails"] == 0


def test_a_success_without_earlier_failures_adds_no_counter_field():
    patches, _ = run_with_prev(scripted({}), {"lize": {"live": {"on": False}}})
    assert "liveFails" not in patches["lize"] and "liveFails" not in patches["tabi"]


@pytest.mark.parametrize("junk", ["3", -2, 0, None, 2.5, True, [], {}])
def test_unreadable_previous_counters_count_as_zero(junk):
    patches, _ = run_with_prev(scripted({"ID_LIZE": [requests.ConnectionError("x")]}), {"lize": {"liveFails": junk}})
    assert patches["lize"] == {"liveFails": 1}


def test_a_failing_member_does_not_touch_the_streak_of_the_others_or_of_members_without_an_id():
    seen = []
    patches, _ = run_with_prev(scripted({"ID_LIZE": [http_error(500)]}), {"lize": {"liveFails": 2}, "tabi": {"liveFails": 2}, "kangji": {"liveFails": 9}},
                               lambda *a: seen.append(a))
    assert patches["tabi"]["liveFails"] == 0 and "kangji" not in patches and "rin" not in patches  # id가 없는 멤버는 건드리지 않는다
    assert [s[0] for s in seen] == ["아카네 리제"]


def test_collect_without_a_streak_callback_or_previous_status_still_works():
    patches, errors = chzzk.collect(MEMBERS, now_iso=NOW_ISO, get=scripted({"ID_LIZE": [http_error(500)]}), sleep=lambda s: None)
    assert patches["lize"] == {"liveFails": 1} and len(errors) == 1
