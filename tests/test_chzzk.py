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


def run(get, sleeps=None):
    return chzzk.collect(MEMBERS, get=get, sleep=(sleeps if sleeps is not None else []).append)


def test_only_members_with_an_id_are_requested():
    get = getter(open_ids={"ID_TABI"})
    patches, errors = run(get)
    assert errors == []
    assert patches["lize"] == {"live": {"on": False}}
    assert patches["tabi"]["live"]["on"] is True and patches["tabi"]["live"]["url"] == config.CHZZK_LIVE_PAGE_URL.format(channel_id="ID_TABI")
    assert set(patches) == {"lize", "tabi"}  # kangji·rin은 결과에 없다 (live 키를 만들어 내지 않는다)
    assert get.calls == [config.CHZZK_LIVE_STATUS_URL.format(channel_id=i) for i in ("ID_LIZE", "ID_TABI")]


def test_pauses_between_requests_but_not_before_the_first():
    sleeps = []
    run(getter(), sleeps)
    assert sleeps == [config.REQUEST_DELAY]  # 2번 요청 → 사이 1번


def test_a_failed_member_is_left_out_so_its_previous_value_survives():
    patches, errors = run(getter(fail={"ID_LIZE": requests.ConnectionError("blocked")}))
    assert "lize" not in patches and "tabi" in patches  # 실패를 {"on": False}로 쓰지 않는다
    assert len(errors) == 1 and "아카네 리제" in errors[0]


def test_http_error_and_bad_json_and_wrong_channel_are_failures():
    resp403 = make_response(403)
    get = getter(
        fail={"ID_LIZE": requests.HTTPError("403", response=resp403)},
        bad_body={"ID_TABI": b"<html>not json</html>"},
    )
    patches, errors = run(get)
    assert patches == {} and len(errors) == 2

    def other_channel(url, **kw):
        d = doc("chzzk_live_close.json")
        d["content"]["channelId"] = "ZZZ"
        return make_response(200, json.dumps(d))

    patches, errors = chzzk.collect(MEMBERS, get=other_channel, sleep=lambda s: None)
    assert patches == {} and len(errors) == 2
