"""공지 일정 자동 추출: 검증·중복 제거·상태 전이·실행 흐름 (기능 3). 네트워크·실제 API 없음 — 가짜 get·FakePost."""
import json
import logging
from datetime import date, datetime

import pytest
import requests

from conftest import FIXTURES, make_response
from fakeclaude import KEY, MODEL, SECRET_BODY, FakePost, error_reply, ev, events_reply, reply
from updater import auto_events as ae
from updater import config, tagging
from updater.sources import claude_events as ce

NOW = datetime(2026, 10, 9, 13, 0, tzinfo=config.KST)
NOW_ISO = "2026-10-09T13:00:00+09:00"
LONG = "공지 본문입니다. " * 10  # 50자 이상


def page(text=LONG):
    return f"<html><body><div class='bh board_list'><div class='bh_title'>목록 제목</div></div><div class='xe_content'><p>{text}</p></div></body></html>".encode("utf-8")


def popup_page():
    return (FIXTURES / "stellive_news_detail_13905.html").read_bytes()


def notice(num, day="2026-09-27", title="<2026 STELLIVE POP-UP STELLA MODE:ON> 안내"):
    return {"id": f"sl-{num}", "date": day, "title": title, "url": f"https://stellive.me/news/{num}", "cat": "공지"}


class Site:
    """가짜 stellive.me/news/<번호>: pages[번호] = bytes | Exception | status(int). 요청한 URL을 기록한다."""

    def __init__(self, pages=None, default=None):
        self.pages, self.default, self.calls = pages or {}, default, []

    def __call__(self, url, **kw):
        self.calls.append(url)
        out = self.pages.get(url.rsplit("/", 1)[1], self.default if self.default is not None else page())
        if isinstance(out, Exception):
            raise out
        if isinstance(out, int):
            raise requests.HTTPError(f"{out} for {url}", response=make_response(out, "x"))
        return make_response(200, out)


@pytest.fixture
def index(members):
    return tagging.build_index(members)


def run(prev, news, post, members, index, *, site=None, now=NOW, sleep=None):
    sleeps = []
    client = ce.Client(KEY, post=post)
    res = ae.run(prev, news, members=members, index=index, client=client, now=now, now_iso=now.isoformat(timespec="seconds"),
                 get=site or Site(), sleep=sleep or sleeps.append)
    res.sleeps = sleeps
    res.client = client
    return res


def doc(items=(), processed=None):
    return {"updatedAt": None, "processed": dict(processed or {}), "items": list(items)}


# ---------------------------------------------------------------- 날짜·문자열
@pytest.mark.parametrize("value,iso,timed", [
    ("2026-10-23", "2026-10-23", False),
    ("2026-10-12T20:00+09:00", "2026-10-12T20:00:00+09:00", True),
    ("2026-10-12T20:00:00+09:00", "2026-10-12T20:00:00+09:00", True),
    ("2026-10-12 20:00", "2026-10-12T20:00:00+09:00", True),  # 오프셋이 없으면 KST
    ("2026-10-12T11:00:00Z", "2026-10-12T20:00:00+09:00", True),  # 다른 오프셋은 KST로
    ("2026-10-12T20:00+0900", "2026-10-12T20:00:00+09:00", True),
    (" 2026-10-23 ", "2026-10-23", False),
])
def test_parse_when_accepts_date_or_datetime_and_normalizes_to_kst(value, iso, timed):
    w = ae.parse_when(value)
    assert (w.iso, w.timed) == (iso, timed)


@pytest.mark.parametrize("value", [None, 20261023, "", "10/23", "2026-13-01", "2026-02-30", "2026-10-12T25:00", "내일", "2026-10", "2026-10-12T20"])
def test_parse_when_rejects_everything_else(value):
    with pytest.raises(ValueError):
        ae.parse_when(value)


def test_clean_text_strips_control_and_invisible_characters_and_checks_length():
    assert ae.clean_text("a​b \x00 c\n d", 20) == "a b c d"
    assert ae.clean_text("", 5) is None and ae.clean_text("   ", 5) is None and ae.clean_text(5, 5) is None and ae.clean_text(None, 5) is None
    assert ae.clean_text("가" * 5, 5) == "가" * 5 and ae.clean_text("가" * 6, 5) is None


def test_norm_title_keeps_only_letters_and_digits():
    assert ae.norm_title("<STELLA MODE:ON>  팝업스토어!") == "stellamodeon팝업스토어"
    assert ae.norm_title("『!!!』") == ""


@pytest.mark.parametrize("text,expected", [
    ("STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 굿즈 판매 마감", "stellive여름신의상공개기념아크릴스탠드"),
    ("STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 판매 마감", "stellive여름신의상공개기념아크릴스탠드"),
    ("2026 STELLIVE POP-UP STELLA MODE:ON", "stellivepopupstellamodeon"), ("2026년 팝업 안내 공지", "년팝업"),
    ("예약 오픈 안내", ""), ("굿즈 판매 마감", ""), ("공지", ""), ("『!!!』", ""),
    ("20261023 일정", "20261023일정"), ("a2026b", "ab"), ("2026 2027 2028", ""), ("1999 콘서트", "콘서트"), ("12345 콘서트", "12345콘서트"), ("2026", ""),
    ("판굿즈매", "판매"),  # 한 번만 훑는다 — 뺀 자리에서 새로 생긴 단어는 다시 빼지 않는다 (사이트의 한 번짜리 replace와 같은 동작)
])
def test_match_title_drops_years_and_common_words_on_top_of_norm_title(text, expected):
    assert ae.match_title(text) == expected


def test_match_title_uses_the_configured_word_list():
    from updater import config
    assert config.EVENT_TITLE_STOPWORDS == ("굿즈", "판매", "마감", "예약", "오픈", "안내", "공지")  # 사이트 matchTitle(index.html)의 목록과 같아야 한다 (test_site_logic이 결과를 비교)
    assert all(ae.match_title(w) == "" for w in config.EVENT_TITLE_STOPWORDS)


def test_valid_who_keys_are_members_groups_and_all_but_not_boss(members):
    keys = ae.valid_who_keys(members)
    assert {"lize", "kangji", "everys", "universe", "cliche", "all"} <= keys and "boss" not in keys


# ---------------------------------------------------------------- 검증
def validate(raw, members, index, *, day=date(2026, 9, 27), title="<STELLA MODE:ON> 팝업 안내"):
    return ae.validate_events(raw, notice_id="sl-1", notice_title=title, notice_day=day, members=members, index=index)


def test_a_good_event_is_normalized_and_keeps_only_known_fields(members, index):
    v = validate([ev("Popup", " STELLA  MODE:ON 팝업스토어 ", "2026-10-23", end="2026-11-01", time="10:00–20:00", place="서울 광진구 광나루로 441",
                     url="http://evil.example", id="x", extra=1)], members, index)
    assert v.events == [{"kind": "popup", "title": "STELLA MODE:ON 팝업스토어", "start": "2026-10-23", "end": "2026-11-01",
                         "time": "10:00–20:00", "place": "서울 광진구 광나루로 441", "who": ["all"]}]
    assert v.dropped == 0


@pytest.mark.parametrize("cand", [
    "문자열", None, [], {"title": "x", "start": "2026-10-23"}, ev("party"), ev(kind=None), ev(title=""), ev(title="가" * 61), ev(title=5),
    ev(start="내일"), ev(start=None), ev(start="2026-10-23", end="어제"), ev(start="2026-10-23", end="2026-10-22"),
])
def test_bad_candidates_are_dropped_and_counted(cand, members, index, caplog):
    with caplog.at_level(logging.WARNING):
        v = validate([cand], members, index)
    assert v.events == [] and v.dropped == 1 and "일정 후보를 버림" in caplog.text


def test_title_length_limit_is_inclusive_and_trims_spaces_first(members, index):
    assert len(validate([ev(title="가" * 60)], members, index).events) == 1
    assert len(validate([ev(title="  " + "가" * 60 + "  ")], members, index).events) == 1


@pytest.mark.parametrize("start,ok", [
    ("2026-09-20", True), ("2026-09-19", False),  # 공지 날짜(2026-09-27) −7일까지
    ("2027-09-27", True), ("2027-09-28", False),  # +365일까지
])
def test_start_must_be_within_the_window_around_the_notice_date(start, ok, members, index):
    assert bool(validate([ev(start=start)], members, index).events) is ok


def test_end_rules(members, index):
    # end ≥ start, 하루짜리는 end를 두지 않는다, 너무 먼 end는 버린다
    assert "end" not in validate([ev(start="2026-10-23", end="2026-10-23")], members, index).events[0]
    assert "end" not in validate([ev(start="2026-10-12T20:00+09:00", end="2026-10-12T20:00+09:00")], members, index).events[0]
    assert "end" not in validate([ev(start="2026-10-12T20:00+09:00", end="2026-10-12")], members, index).events[0]
    assert validate([ev(start="2026-10-23", end="2026-11-01")], members, index).events[0]["end"] == "2026-11-01"
    assert validate([ev(start="2026-10-12T20:00+09:00", end="2026-10-12T22:00+09:00")], members, index).events[0]["end"] == "2026-10-12T22:00:00+09:00"
    assert validate([ev(start="2026-10-12T20:00+09:00", end="2026-10-12T19:00+09:00")], members, index).events == []
    assert validate([ev(start="2026-10-23", end="2027-10-24")], members, index).events[0]["end"] == "2027-10-24"  # 간격 366일까지
    assert validate([ev(start="2026-10-23", end="2027-10-25")], members, index).events == []


def test_empty_end_is_the_same_as_no_end(members, index):
    for empty in (None, ""):
        assert "end" not in validate([ev(end=empty)], members, index).events[0]


@pytest.mark.parametrize("who", [["nobody"], ["lize", "nobody"], [], "all", None, ["boss"], [1], ["lize", None]])
def test_invalid_who_is_replaced_by_tagging_the_notice_title(who, members, index):
    cand = ev()
    cand["who"] = who
    v = validate([cand], members, index, title="2026 아카네 리제 생일 한정 굿즈 예약 판매 오픈")
    assert v.events[0]["who"] == ["lize"]


def test_missing_who_falls_back_to_tagging_and_valid_who_is_kept_without_duplicates(members, index):
    cand = ev()
    del cand["who"]
    assert validate([cand], members, index, title="아무 이름도 없는 공지").events[0]["who"] == ["all"]
    cand["who"] = ["lize", "universe", "lize", "all"]
    assert validate([cand], members, index).events[0]["who"] == ["lize", "universe", "all"]


def test_optional_fields_are_cleaned_or_left_out(members, index):
    e = validate([ev(time="가" * 31, place=5)], members, index).events[0]
    assert "time" not in e and "place" not in e  # 너무 길거나 문자열이 아니면 그 필드만 뺀다 (일정은 유지)
    e = validate([ev(time=" 10:00–20:00 ", place="  ")], members, index).events[0]
    assert e["time"] == "10:00–20:00" and "place" not in e


def test_more_than_five_events_per_notice_keeps_the_first_five(members, index):
    raw = [ev(title=f"일정 {i}", start=f"2026-10-{10 + i}") for i in range(7)]
    v = validate(raw, members, index)
    assert [e["title"] for e in v.events] == [f"일정 {i}" for i in range(5)] and v.dropped == 2


def test_exact_duplicates_inside_one_notice_are_merged_but_similar_ones_are_not(members, index):
    v = validate([ev(), ev(), ev(title="STELLA MODE:ON 팝업스토어 2")], members, index)
    assert len(v.events) == 2 and v.dropped == 1


def test_hallucinated_dates_are_dropped_while_valid_siblings_survive(members, index):
    v = validate([ev(start="2031-01-01"), ev(title="진짜", start="2026-10-23")], members, index)
    assert [e["title"] for e in v.events] == ["진짜"] and v.dropped == 1


# ---------------------------------------------------------------- 자동 일정끼리 중복 (사용자 결정)
def item(source="sl-1", kind="popup", title="STELLA MODE:ON 팝업스토어", start="2026-10-23", end=None, **extra):
    d = {"id": f"auto-{source}-1", "source": source, "kind": kind, "title": title, "start": start, "who": ["all"], **extra}
    if end:
        d["end"] = end
    return d


@pytest.mark.parametrize("a,b,expected", [
    # start·end가 같고 + (제목 포함 | kind 같음)
    (item(), item(title="STELLA MODE:ON 팝업스토어 운영 안내"), True),  # 제목 포함, kind 같음
    (item(kind="popup", title="팝업스토어 운영"), item(kind="other", title="[STELLA MODE:ON] 팝업스토어 운영 안내!"), True),  # kind 다르지만 제목 포함
    (item(kind="popup", title="사전 예약 안내"), item(kind="popup", title="현장 운영 방식"), True),  # 제목은 달라도 kind가 같다
    (item(kind="popup", title="사전 예약 안내"), item(kind="reservation", title="현장 운영 방식"), False),  # kind도 제목도 다름
    (item(kind="concert", title="리제 콘서트"), item(kind="concert", title="앙코르 공연"), True),
    (item(kind="broadcast", title="에버리스 방송"), item(kind="broadcast", title="기념 라이브"), True),
    (item(kind="reservation", title="예약 오픈"), item(kind="reservation", title="티켓 오픈"), True),
    # goods·other: kind가 같다는 이유로는 합치지 않는다 (같은 날 마감인 서로 다른 굿즈)
    (item(kind="goods", title="타비 생일 굿즈 판매 마감"), item(kind="goods", title="나나 생일 굿즈 판매 마감"), False),
    (item(kind="other", title="포토이즘 콜라보 프레임"), item(kind="other", title="콜라보 카페 이벤트"), False),
    (item(kind="goods", title="타비 굿즈 판매 마감"), item(kind="goods", title="2026 아라하시 타비 생일 굿즈 판매 마감"), True),  # 제목이 포함되면 합친다
    (item(kind="goods", title="굿즈 판매 마감"), item(kind="goods", title="타비 생일 굿즈 판매 마감"), False),  # 흔한 단어를 빼면 빈 제목이라 합치지 않는다 (사용자 규칙 2026-10-10)
    # 흔한 단어·연도를 뺀 제목으로 비교 (사용자 결정 2026-10-10)
    (item(kind="goods", title="STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 굿즈 판매 마감", start="2026-10-04"),
     item(kind="goods", title="STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 판매 마감", start="2026-10-04"), True),  # 10/4 신의상 스탠드: '굿즈' 한 단어 차이
    (item(kind="goods", title="타비 생일 굿즈 마감"), item(kind="goods", title="나나 생일 굿즈 마감"), False),  # 같은 날 다른 굿즈는 둘 다 남는다
    (item(kind="goods", title="타비 생일 굿즈 판매 마감"), item(kind="goods", title="나나 생일 굿즈 판매 마감 안내"), False),
    (item(kind="other", title="2026 포토이즘 콜라보 프레임"), item(kind="other", title="포토이즘 콜라보 프레임 안내"), True),  # 연도·안내를 빼면 같다
    (item(kind="other", title="예약 오픈 안내"), item(kind="other", title="오픈 공지"), False),  # 둘 다 흔한 단어뿐 → 빈 제목 → 합치지 않는다
    (item(kind="other", title="포토이즘 콜라보"), item(kind="other", title="[포토이즘 콜라보] 프레임 안내"), True),
    (item(kind="goods", title="!!!"), item(kind="goods", title="타비 굿즈 판매 마감"), False),  # 기호뿐인 제목은 포함으로도 합쳐지지 않는다
    # start·end가 다르면 아무것도 보지 않는다
    (item(start="2026-10-23"), item(start="2026-10-24"), False),
    (item(end="2026-11-01"), item(end="2026-11-02"), False),
    (item(end="2026-11-01"), item(), False),  # 한쪽만 end
    (item(start="2026-10-12T20:00:00+09:00"), item(start="2026-10-12"), False),  # 시각 포함과 날짜만은 다르다 (문자 그대로 비교)
    (item(start="2026-10-12T20:00:00+09:00", kind="reservation"), item(start="2026-10-12T20:00:00+09:00", kind="reservation", title="예약 오픈"), True),
])
def test_is_duplicate_table(a, b, expected):
    assert ae.is_duplicate(a, b) is expected and ae.is_duplicate(b, a) is expected  # 대칭


def test_empty_normalized_title_never_matches_by_containment():
    """기호뿐인 제목은 정규화하면 ''이고 ''는 모든 문자열에 들어 있다 — 그걸로 중복 판정하면 안 된다."""
    assert ae.is_duplicate(item(kind="popup", title="!!!"), item(kind="other", title="STELLA MODE:ON")) is False
    assert ae.is_duplicate(item(kind="popup", title="!!!"), item(kind="popup", title="STELLA MODE:ON")) is True  # kind가 같으면 같다
    # 흔한 단어뿐인 제목도 정규화하면 ''이다 — 같은 규칙
    assert ae.is_duplicate(item(kind="goods", title="굿즈 판매 마감"), item(kind="goods", title="신의상 스탠드 굿즈 판매 마감")) is False
    assert ae.is_duplicate(item(kind="other", title="굿즈 판매 마감"), item(kind="other", title="2026 안내")) is False
    assert ae.is_duplicate(item(kind="popup", title="예약 오픈"), item(kind="popup", title="사전 신청")) is True  # kind가 같으면(popup) 같다


def test_find_duplicate_only_looks_at_other_notices():
    stored = [item(source="sl-1")]
    assert ae.find_duplicate(item(source="sl-2"), stored) is stored[0]
    assert ae.find_duplicate(item(source="sl-1"), stored) is None  # 같은 공지 안의 일정끼리는 이 규칙을 적용하지 않는다


# ---------------------------------------------------------------- 대상 선정
def test_targets_are_oldest_first_by_notice_number_within_45_days_and_capped_at_five():
    news = [notice(i, day=f"2026-10-0{i}") for i in range(1, 8)] + [notice(99, day="2026-08-25"), notice(98, day="2026-08-24")]  # 45일·46일 전
    got = [n["id"] for n in ae.select_targets(news, {}, date(2026, 10, 9))]
    assert got == ["sl-1", "sl-2", "sl-3", "sl-4", "sl-5"]  # 5개 상한, 오래된(번호가 작은) 공지부터 — 사용자 결정 2026-10-09
    got = [n["id"] for n in ae.select_targets([notice(99, day="2026-08-25"), notice(98, day="2026-08-24")], {}, date(2026, 10, 9))]
    assert got == ["sl-99"]  # 45일 전은 포함, 46일 전은 제외


def test_the_order_is_by_notice_number_not_by_date():
    news = [notice(300, day="2026-09-28"), notice(100, day="2026-10-08"), notice(200, day="2026-10-01")]  # 번호와 날짜 순서가 어긋나도 번호가 기준
    assert [n["id"] for n in ae.select_targets(news, {}, date(2026, 10, 9))] == ["sl-100", "sl-200", "sl-300"]
    assert [n["id"] for n in ae.select_targets([notice(100), notice(300), notice(200)], {}, date(2026, 10, 9))] == ["sl-100", "sl-200", "sl-300"]


def test_only_notices_are_targets_and_unreadable_dates_are_skipped():
    news = [{"id": "yt-abc", "date": "2026-10-08"}, {"id": "mu-1", "date": "2026-10-08"}, {"id": "sl-x", "date": "2026-10-08"},
            {"id": "sl-5", "date": "나중에"}, {"id": "sl-6"}, notice(7, day="2026-10-08")]
    assert [n["id"] for n in ae.select_targets(news, {}, date(2026, 10, 9))] == ["sl-7"]


@pytest.mark.parametrize("record,picked", [
    ({"result": "events", "tries": 1}, False), ({"result": "none", "tries": 1}, False), ({"result": "no_text", "tries": 1}, False),  # 영구
    ({"result": "error", "tries": 1}, True), ({"result": "error", "tries": 2}, True), ({"result": "error", "tries": 3}, False),  # 3회까지
    ("이상한 값", False),
])
def test_processed_records_decide_whether_a_notice_is_a_target_again(record, picked):
    assert bool(ae.select_targets([notice(1, day="2026-10-08")], {"sl-1": record}, date(2026, 10, 9))) is picked


def test_error_retries_share_the_five_slot_cap_with_new_notices():
    news = [notice(i, day=f"2026-10-0{i}") for i in range(1, 8)]
    processed = {"sl-1": {"result": "error", "tries": 1}, "sl-2": {"result": "error", "tries": 1}}
    got = [n["id"] for n in ae.select_targets(news, processed, date(2026, 10, 9))]
    assert got == ["sl-1", "sl-2", "sl-3", "sl-4", "sl-5"]  # 오래된 공지부터라 error 재시도(1·2)가 먼저 가고 새 공지는 뒤로 밀린다


# ---------------------------------------------------------------- 보관
def test_items_are_kept_for_30_days_after_they_end_and_processed_for_90():
    today = date(2026, 12, 1)
    d = doc(
        items=[item("sl-1", start="2026-10-23", end="2026-11-01", id="a"),   # 끝난 지 30일 → 유지
               item("sl-2", start="2026-10-23", end="2026-10-31", id="b"),   # 31일 → 삭제
               item("sl-3", start="2026-11-01", id="c"),                    # end 없음 → start 기준 30일 → 유지
               item("sl-4", start="2026-10-31", id="d")],                   # 31일 → 삭제
        processed={"sl-1": {"at": "2026-09-02T13:00:00+09:00", "result": "events", "tries": 1},    # 90일 전 → 유지
                   "sl-2": {"at": "2026-09-01T12:59:00+09:00", "result": "events", "tries": 1},    # 90일 넘음 → 삭제
                   "sl-3": {"at": "깨진 값", "result": "events", "tries": 1}})                      # 읽을 수 없음 → 삭제
    now = datetime(2026, 12, 1, 13, 0, tzinfo=config.KST)
    removed_items, removed_processed = ae.prune(d, today, now)
    assert sorted(i["source"] for i in d["items"]) == ["sl-1", "sl-3"] and removed_items == 2
    assert sorted(d["processed"]) == ["sl-1"] and removed_processed == 2


# ---------------------------------------------------------------- 실행 흐름
def test_a_popup_notice_becomes_items_with_the_notice_url_and_a_processed_record(members, index):
    post = FakePost(events_reply(
        ev("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", end="2026-11-01", time="10:00–20:00", place="서울 광진구 광나루로 441", url="http://evil.example"),
        ev("reservation", "팝업스토어 예약 오픈", "2026-10-12T20:00+09:00"),
        ev("other", "포토이즘 콜라보 프레임", "2026-10-23", end="2026-11-05")))
    r = run(doc(), [notice(13905)], post, members, index, site=Site({"13905": popup_page()}))
    assert [(i["id"], i["kind"], i["start"]) for i in r.doc["items"]] == [
        ("auto-sl-13905-2", "reservation", "2026-10-12T20:00:00+09:00"), ("auto-sl-13905-1", "popup", "2026-10-23"), ("auto-sl-13905-3", "other", "2026-10-23")]
    assert all(i["url"] == "https://stellive.me/news/13905" and i["source"] == "sl-13905" for i in r.doc["items"])  # 모델이 낸 url은 무시
    assert list(r.doc["items"][1]) == ["id", "source", "kind", "title", "start", "end", "time", "place", "who", "url"]
    assert r.doc["processed"] == {"sl-13905": {"at": NOW_ISO, "result": "events", "tries": 1}}
    assert sorted(i["id"] for i in r.fresh) == sorted(i["id"] for i in r.doc["items"])  # 새로 저장된 것이 곧 알림 판정 입력
    assert r.report.events == 1 and r.report.new_items == 3 and r.report.api_calls == 1 and r.report.model == MODEL
    assert "Colorful" not in json.dumps(r.doc)


def test_the_popup_fixture_body_is_what_the_model_is_given(members, index):
    post = FakePost(events_reply())
    run(doc(), [notice(13905)], post, members, index, site=Site({"13905": popup_page()}))
    user = post.calls[0][1]["messages"][0]["content"]
    assert "2026년 10월 12일 (월) 오후 8시" in user and "광나루로 441" in user and "[공지 날짜] 2026-09-27" in user
    assert "생일 한정 굿즈 판매 마감 임박 안내" not in user  # 상세 페이지에 같이 들어 있는 목록(첫 항목 제목)은 모델에 가지 않는다


def test_no_events_is_recorded_as_none(members, index):
    r = run(doc(), [notice(1)], FakePost(events_reply()), members, index)
    assert r.doc["processed"]["sl-1"] == {"at": NOW_ISO, "result": "none", "tries": 1} and r.doc["items"] == [] and r.report.none == 1


def test_all_candidates_failing_validation_is_none_too(members, index):
    r = run(doc(), [notice(1)], FakePost(events_reply(ev(start="2031-01-01"), ev(kind="party"))), members, index)
    assert r.doc["processed"]["sl-1"]["result"] == "none" and r.report.dropped == 2


def test_image_only_notice_is_no_text_and_the_api_is_not_called(members, index):
    post = FakePost(events_reply(ev()))
    site = Site({"13838": (FIXTURES / "stellive_news_detail_imageonly_13838.html").read_bytes()})
    r = run(doc(), [notice(13838)], post, members, index, site=site)
    assert r.doc["processed"]["sl-13838"] == {"at": NOW_ISO, "result": "no_text", "tries": 1}
    assert post.calls == [] and r.report.no_text == 1 and r.report.api_calls == 0
    again = run(r.doc, [notice(13838)], post, members, index, site=site)  # 영구: 다시 보지 않는다
    assert again.report.targets == 0 and post.calls == []


def test_body_just_under_and_at_the_no_text_threshold(members, index):
    under = Site({"1": page("가" * 49)})
    at = Site({"2": page("가" * 50)})
    post = FakePost(events_reply())
    assert run(doc(), [notice(1)], post, members, index, site=under).report.no_text == 1 and post.calls == []
    assert run(doc(), [notice(2)], post, members, index, site=at).report.none == 1 and len(post.calls) == 1


def test_broken_model_output_is_retried_once_then_error_with_a_try_count_up_to_three_runs(members, index):
    post = FakePost(reply("모르겠어요"))
    news = [notice(1, day="2026-10-08")]
    r1 = run(doc(), news, post, members, index)
    assert r1.doc["processed"]["sl-1"] == {"at": NOW_ISO, "result": "error", "tries": 1} and r1.report.api_calls == 2  # 호출 2번(재시도 1회)
    r2 = run(r1.doc, news, post, members, index)
    assert r2.doc["processed"]["sl-1"]["tries"] == 2
    r3 = run(r2.doc, news, post, members, index)
    assert r3.doc["processed"]["sl-1"]["tries"] == 3 and r3.report.error == 1
    r4 = run(r3.doc, news, post, members, index)  # 3회로 끝
    assert r4.report.targets == 0 and len(post.calls) == 6


def test_a_retry_that_succeeds_replaces_the_error_record(members, index):
    news = [notice(1, day="2026-10-08")]
    r1 = run(doc(), news, FakePost(reply("???")), members, index)
    r2 = run(r1.doc, news, FakePost(events_reply(ev())), members, index)
    assert r2.doc["processed"]["sl-1"]["result"] == "events" and r2.doc["processed"]["sl-1"]["tries"] == 2 and len(r2.doc["items"]) == 1


@pytest.mark.parametrize("outcome,cls,label", [
    (error_reply(401, "authentication_error"), ce.KeyRejected, "HTTP 401 authentication_error"),
    (error_reply(400, "invalid_request_error"), ce.RequestRejected, "HTTP 400 invalid_request_error"),
    (error_reply(429, "rate_limit_error"), ce.Unavailable, "HTTP 429 rate_limit_error"),
    (error_reply(529, "overloaded_error"), ce.Unavailable, "HTTP 529 overloaded_error"),
    (requests.ConnectionError("x"), ce.Unavailable, "ConnectionError"),
])
def test_api_errors_stop_the_run_without_recording_anything_so_tries_are_not_used_up(outcome, cls, label, members, index):
    post = FakePost(outcome)
    news = [notice(i, day=f"2026-10-0{i}") for i in range(1, 4)]
    r = run(doc(), news, post, members, index)
    assert r.doc["processed"] == {} and r.doc["items"] == [] and len(post.calls) == 1  # 첫 오류에서 멈춘다 (남은 공지는 부르지 않는다)
    assert isinstance(r.report.abort, cls) and str(r.report.abort) == label and r.report.deferred == 1
    again = run(r.doc, news, FakePost(events_reply()), members, index)  # 다음 실행: 모두 다시 대상
    assert again.report.targets == 3 and again.report.none == 3


def test_api_error_midway_keeps_what_was_already_processed(members, index):
    post = FakePost(events_reply(ev(title="첫번째 일정")), error_reply(500))
    news = [notice(3, day="2026-10-03"), notice(2, day="2026-10-02"), notice(1, day="2026-10-01")]
    r = run(doc(), news, post, members, index)
    assert list(r.doc["processed"]) == ["sl-1"] and [i["title"] for i in r.doc["items"]] == ["첫번째 일정"] and len(post.calls) == 2  # 오래된 공지(sl-1)부터


@pytest.mark.parametrize("page_outcome,result", [(404, "error"), (403, "error"), (410, "error")])
def test_4xx_detail_pages_are_errors_with_a_try_count(page_outcome, result, members, index):
    post = FakePost(events_reply())
    r = run(doc(), [notice(1)], post, members, index, site=Site({"1": page_outcome}))
    assert r.doc["processed"]["sl-1"]["result"] == result and post.calls == [] and r.report.error == 1


@pytest.mark.parametrize("page_outcome", [500, 503, 429, 408, requests.ConnectionError("x"), requests.Timeout("x")])
def test_transient_detail_page_failures_are_not_recorded(page_outcome, members, index):
    post = FakePost(events_reply())
    r = run(doc(), [notice(1)], post, members, index, site=Site({"1": page_outcome}))
    assert r.doc["processed"] == {} and post.calls == [] and r.report.deferred == 1 and r.report.abort is None


def test_a_page_without_the_body_container_is_an_error_not_no_text(members, index):
    r = run(doc(), [notice(1)], FakePost(events_reply()), members, index, site=Site({"1": b"<html><body>Access denied</body></html>"}))
    assert r.doc["processed"]["sl-1"]["result"] == "error" and r.report.no_text == 0


def test_a_failing_notice_does_not_block_the_next_one(members, index):
    post = FakePost(events_reply(ev(title="살아남은 일정")))
    r = run(doc(), [notice(2, day="2026-10-02"), notice(1, day="2026-10-01")], post, members, index, site=Site({"2": 500}))
    assert [i["title"] for i in r.doc["items"]] == ["살아남은 일정"] and r.report.deferred == 1


def test_at_most_five_notices_per_run_and_the_rest_next_time(members, index):
    news = [notice(i, day=f"2026-10-0{i}") for i in range(1, 8)]
    post = FakePost(events_reply())
    r1 = run(doc(), news, post, members, index)
    assert r1.report.targets == 5 and len(post.calls) == 5 and sorted(r1.doc["processed"]) == ["sl-1", "sl-2", "sl-3", "sl-4", "sl-5"]
    r2 = run(r1.doc, news, post, members, index)
    assert r2.report.targets == 2 and sorted(r2.doc["processed"]) == [f"sl-{i}" for i in range(1, 8)]
    assert run(r2.doc, news, post, members, index).report.targets == 0


def test_second_run_on_the_same_state_makes_no_requests_at_all(members, index):
    news = [notice(i, day=f"2026-10-0{i}") for i in range(1, 4)]
    post, site = FakePost(events_reply(ev())), Site()
    r1 = run(doc(), news, post, members, index, site=site)
    n_posts, n_gets = len(post.calls), len(site.calls)
    r2 = run(r1.doc, news, post, members, index, site=site)
    assert (len(post.calls), len(site.calls)) == (n_posts, n_gets) and r2.fresh == [] and r2.report.api_calls == 0 and r2.doc["items"] == r1.doc["items"]


def test_requests_to_the_site_are_spaced_by_the_request_delay(members, index):
    r = run(doc(), [notice(i, day=f"2026-10-0{i}") for i in range(1, 4)], FakePost(events_reply()), members, index)
    assert r.sleeps == [config.REQUEST_DELAY, config.REQUEST_DELAY]  # 3건 → 간격 2번


def test_previous_state_is_not_modified(members, index):
    prev = doc(items=[item(id="auto-sl-9-1", source="sl-9")], processed={"sl-9": {"at": NOW_ISO, "result": "events", "tries": 1}})
    snapshot = json.dumps(prev, sort_keys=True)
    run(prev, [notice(1, day="2026-10-08")], FakePost(events_reply(ev(title="다른 일정", start="2026-10-30"))), members, index)
    assert json.dumps(prev, sort_keys=True) == snapshot


def test_goods_deadline_notice_makes_one_goods_event(members, index):
    news = [notice(14073, day="2026-10-07", title="2026 아라하시 타비 생일 한정 굿즈 판매 마감 임박 안내")]
    post = FakePost(events_reply({"kind": "goods", "title": "아라하시 타비 생일 굿즈 판매 마감", "start": "2026-10-07", "time": "23:59", "who": ["tabi"]}))
    site = Site({"14073": (FIXTURES / "stellive_news_detail_goods_14073.html").read_bytes()})
    r = run(doc(), news, post, members, index, site=site)
    assert r.doc["items"][0]["kind"] == "goods" and r.doc["items"][0]["who"] == ["tabi"] and r.doc["items"][0]["time"] == "23:59"
    assert "23시 59분까지" in post.calls[0][1]["messages"][0]["content"]


# ---------------------------------------------------------------- 자동 일정끼리 중복 제거 (실행 흐름)
def test_same_popup_in_several_notices_is_kept_once_from_the_original_notice_processed_first(members, index):
    """13905·13907·13930·13962 — 모두 같은 팝업 기간을 말한다. 오래된 공지(번호 오름차순)부터 처리하므로 원 공지(13905)의 일정 하나만 남고 나머지는 저장도 알림도 되지 않는다."""
    popup = dict(end="2026-11-01")
    post = FakePost(   # 처리 순서: 13905 → 13907 → 13930 → 13962
        events_reply(ev("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", **popup), ev("reservation", "팝업 예약 오픈", "2026-10-12T20:00+09:00")),   # 13905(원 공지)
        events_reply(ev("popup", "<STELLA MODE:ON> 팝업 현장 픽업 서비스", "2026-10-23", **popup)),                                              # 같은 start·end, kind 같음
        events_reply(ev("other", "STELLA MODE:ON 팝업스토어 1차 MD", "2026-10-23", **popup)),                                                   # kind 다르지만 제목 포함
        events_reply(ev("popup", "팝업스토어 이용 FAQ", "2026-10-24", end="2026-11-01")))                                                        # start가 다르면 유지
    news = [notice(13962, day="2026-09-28"), notice(13930, day="2026-09-28"), notice(13907), notice(13905)]
    r = run(doc(), news, post, members, index)
    sources = [(i["source"], i["kind"], i["start"][:10]) for i in r.doc["items"]]
    assert sources == [("sl-13905", "reservation", "2026-10-12"), ("sl-13905", "popup", "2026-10-23"), ("sl-13962", "popup", "2026-10-24")]
    assert r.report.duplicates == 2 and r.report.new_items == 3
    assert sorted(i["id"] for i in r.fresh) == sorted(i["id"] for i in r.doc["items"]) and len(r.fresh) == 3  # 알림 후보도 이 3개뿐
    # 중복으로 걸러진 공지도 처리 완료다 (다시 부르지 않는다)
    assert all(r.doc["processed"][f"sl-{n}"]["result"] == "events" for n in (13962, 13930, 13907, 13905))


def test_the_notices_are_processed_in_ascending_number_order(members, index):
    site = Site()
    run(doc(), [notice(300, day="2026-10-01"), notice(100, day="2026-10-05"), notice(200, day="2026-10-03")], FakePost(events_reply()), members, index, site=site)
    assert [u.rsplit("/", 1)[1] for u in site.calls] == ["100", "200", "300"]


def test_the_first_backfill_keeps_the_original_notice_even_when_newer_notices_say_the_same(members, index):
    """실제 사례의 모사(3-2): 14073·13962·13930·13907·13905를 한 번에 백필하면 popup·reservation은 원 공지 13905의 것이 남고, 뒤 공지(FAQ 13962)는 중복으로 걸러진다."""
    news = [notice(14073, "2026-10-07"), notice(13962, "2026-09-28"), notice(13930, "2026-09-28"), notice(13907, "2026-09-27"), notice(13905, "2026-09-27")]
    popup = ev("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", end="2026-11-01")
    rsv = ev("reservation", "팝업스토어 예약 오픈", "2026-10-12T20:00+09:00")
    post = FakePost(
        events_reply(rsv, popup, ev("other", "포토이즘 콜라보 프레임", "2026-10-23", end="2026-11-05")),   # 13905
        events_reply(),                                                                                     # 13907
        events_reply(),                                                                                     # 13930
        events_reply(ev("popup", "2026 STELLIVE POP-UP STELLA MODE:ON", "2026-10-23", end="2026-11-01"), ev("reservation", "사전 예약 오픈", "2026-10-12T20:00+09:00")),  # 13962
        events_reply(ev("goods", "타비 생일 굿즈 판매 마감", "2026-10-07")))                                  # 14073
    r = run(doc(), news, post, members, index)
    kept = {(i["kind"], i["source"]) for i in r.doc["items"]}
    assert ("popup", "sl-13905") in kept and ("reservation", "sl-13905") in kept and ("other", "sl-13905") in kept and ("goods", "sl-14073") in kept
    assert not any(src == "sl-13962" for _, src in kept) and len(r.doc["items"]) == 4 and r.report.duplicates == 2
    assert all(i["url"] in ("https://stellive.me/news/13905", "https://stellive.me/news/14073") for i in r.doc["items"])


def test_across_several_runs_a_lower_numbered_notice_is_always_processed_before_a_higher_one(members, index):
    """첫 백필이 여러 실행에 걸쳐도(5건 상한) 처리 순서는 번호 오름차순이다 — 그래서 어느 실행에서든 원 공지가 뒤 공지보다 먼저 저장된다."""
    numbers = [13700 + 7 * i for i in range(13)]
    news = [notice(n, day="2026-10-05") for n in reversed(numbers)]
    site, state, seen = Site(), doc(), []
    for _ in range(4):
        before = len(site.calls)
        state = run(state, news, FakePost(events_reply()), members, index, site=site).doc
        seen += [int(u.rsplit("/", 1)[1]) for u in site.calls[before:]]
    assert seen == numbers and len(state["processed"]) == 13  # 5 + 5 + 3, 중복 요청 없음


def test_the_stored_item_wins_over_a_later_notice_across_runs_and_the_dropped_one_is_not_alerted(members, index):
    r1 = run(doc(), [notice(13905)], FakePost(events_reply(ev("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", end="2026-11-01"))), members, index)
    r2 = run(r1.doc, [notice(13905), notice(13962, day="2026-09-28")],
             FakePost(events_reply(ev("popup", "팝업스토어 이용 FAQ", "2026-10-23", end="2026-11-01"))), members, index)
    assert [i["source"] for i in r2.doc["items"]] == ["sl-13905"] and r2.fresh == [] and r2.report.duplicates == 1
    assert r2.doc["processed"]["sl-13962"]["result"] == "events"


def test_events_of_the_same_notice_are_not_deduplicated_against_each_other(members, index):
    """같은 공지가 같은 날 마감인 굿즈 두 개를 말하면 둘 다 남는다 (중복 제거는 다른 공지 사이에서만)."""
    post = FakePost(events_reply(ev("goods", "타비 굿즈 판매 마감", "2026-10-07"), ev("goods", "나나 굿즈 판매 마감", "2026-10-07")))
    r = run(doc(), [notice(1, day="2026-10-07")], post, members, index)
    assert len(r.doc["items"]) == 2 and r.report.duplicates == 0


def test_a_separate_event_in_the_same_body_is_kept_as_is(members, index):
    """포토이즘 콜라보처럼 같은 본문 안의 별건 일정은 그대로 추출된다 (kind other)."""
    post = FakePost(events_reply(ev("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", end="2026-11-01"),
                                 ev("other", "PHOTOISM X STELLA MODE:ON 콜라보 프레임", "2026-10-23", end="2026-11-05")))
    r = run(doc(), [notice(13905)], post, members, index)
    assert [(i["kind"], i["end"]) for i in r.doc["items"]] == [("popup", "2026-11-01"), ("other", "2026-11-05")]


def test_two_different_goods_with_the_same_deadline_in_different_notices_both_stay(members, index):
    """같은 날 마감인 서로 다른 굿즈(다른 공지)는 둘 다 남는다 — goods는 kind가 같다는 이유로 합치지 않는다 (사용자 수정 2026-10-09)."""
    post = FakePost(events_reply(ev("goods", "나나 생일 굿즈 판매 마감", "2026-10-07")), events_reply(ev("goods", "타비 생일 굿즈 판매 마감", "2026-10-07")))
    r = run(doc(), [notice(2, day="2026-10-07"), notice(1, day="2026-10-07")], post, members, index)
    assert sorted(i["title"] for i in r.doc["items"]) == ["나나 생일 굿즈 판매 마감", "타비 생일 굿즈 판매 마감"] and r.report.duplicates == 0 and len(r.fresh) == 2


def test_the_same_goods_deadline_repeated_by_two_notices_is_still_merged_by_title(members, index):
    """'마감 임박' 공지와 '예약 오픈' 공지가 같은 굿즈의 같은 마감일을 말하면 제목이 포함 관계라 하나만 남는다."""
    post = FakePost(events_reply(ev("goods", "타비 생일 굿즈 판매 마감", "2026-10-07")), events_reply(ev("goods", "2026 아라하시 타비 생일 굿즈 판매 마감", "2026-10-07")))
    r = run(doc(), [notice(2, day="2026-10-07"), notice(1, day="2026-10-07")], post, members, index)
    assert len(r.doc["items"]) == 1 and r.report.duplicates == 1


def test_the_same_goods_deadline_with_and_without_the_word_goods_is_merged(members, index):
    """달력에서 본 문제 (나) 10/4 신의상 스탠드: 13557 '…스탠드 굿즈 판매 마감'과 14028 '…스탠드 판매 마감'은 이제 저장 시점에 하나로 합쳐지고 먼저 처리된 13557이 남는다."""
    t1, t2 = "STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 굿즈 판매 마감", "STELLIVE 여름 신의상 공개 기념 아크릴 스탠드 판매 마감"
    post = FakePost(events_reply(ev("goods", t1, "2026-10-04")), events_reply(ev("goods", t2, "2026-10-04")))
    r = run(doc(), [notice(13557, day="2026-10-01"), notice(14028, day="2026-10-02")], post, members, index)
    assert [(i["source"], i["title"]) for i in r.doc["items"]] == [("sl-13557", t1)] and r.report.duplicates == 1 and len(r.fresh) == 1


def test_birthday_goods_of_different_members_with_the_same_deadline_both_stay(members, index):
    post = FakePost(events_reply(ev("goods", "타비 생일 굿즈 마감", "2026-10-07")), events_reply(ev("goods", "나나 생일 굿즈 마감", "2026-10-07")))
    r = run(doc(), [notice(1, day="2026-10-05"), notice(2, day="2026-10-06")], post, members, index)
    assert sorted(i["title"] for i in r.doc["items"]) == ["나나 생일 굿즈 마감", "타비 생일 굿즈 마감"] and r.report.duplicates == 0


def test_a_title_made_only_of_common_words_is_never_merged_by_containment(members, index):
    post = FakePost(events_reply(ev("goods", "굿즈 판매 마감", "2026-10-07")), events_reply(ev("goods", "타비 생일 굿즈 판매 마감", "2026-10-07")))
    r = run(doc(), [notice(1, day="2026-10-05"), notice(2, day="2026-10-06")], post, members, index)
    assert len(r.doc["items"]) == 2 and r.report.duplicates == 0


def test_inside_one_notice_only_exactly_equal_events_are_merged_even_with_common_words(members, index):
    """같은 공지 안의 '완전히 같은 일정' 판정은 흔한 단어를 빼지 않는다 (norm_title). 서로 다른 일정을 합치면 안 된다."""
    v = validate([ev("goods", "굿즈 판매 마감", "2026-10-07"), ev("goods", "예약 판매 마감", "2026-10-07")], members, index)
    assert len(v.events) == 2 and v.dropped == 0


def test_two_different_other_events_on_the_same_dates_in_different_notices_both_stay(members, index):
    post = FakePost(events_reply(ev("other", "포토이즘 콜라보 프레임", "2026-10-23", end="2026-11-05")), events_reply(ev("other", "콜라보 카페 이벤트", "2026-10-23", end="2026-11-05")))
    r = run(doc(), [notice(2, day="2026-10-08"), notice(1, day="2026-10-07")], post, members, index)
    assert len(r.doc["items"]) == 2 and r.report.duplicates == 0


@pytest.mark.parametrize("kind", ["popup", "concert", "reservation", "broadcast"])
def test_the_kind_rule_still_applies_to_the_four_alert_kinds(kind, members, index):
    post = FakePost(events_reply(ev(kind, "첫 번째 일정", "2026-10-23")), events_reply(ev(kind, "전혀 다른 제목", "2026-10-23")))
    r = run(doc(), [notice(2, day="2026-10-08"), notice(1, day="2026-10-07")], post, members, index)
    assert len(r.doc["items"]) == 1 and r.report.duplicates == 1 and config.EVENT_DEDUP_SAME_KIND == ("popup", "concert", "reservation", "broadcast")


# ---------------------------------------------------------------- 정렬·결정성
def test_items_are_sorted_by_start_then_id_and_processed_by_id(members, index):
    post = FakePost(events_reply(ev(title="나중", start="2026-10-30"), ev(title="먼저", start="2026-10-12T20:00+09:00", kind="reservation")))
    r = run(doc(), [notice(7, day="2026-10-08")], post, members, index)
    assert [i["title"] for i in r.doc["items"]] == ["먼저", "나중"]


# ---------------------------------------------------------------- 비밀·원문
def test_logs_never_contain_the_key_or_response_text_or_body(members, index, caplog):
    secret_page = Site({"1": page(SECRET_BODY * 3)})
    post = FakePost(reply(f"{SECRET_BODY} 일정 아님"), error_reply(401, "authentication_error", f"bad key {KEY} {SECRET_BODY}"))
    with caplog.at_level(logging.DEBUG):
        r = run(doc(), [notice(1, day="2026-10-08"), notice(2, day="2026-10-09")], post, members, index, site=secret_page)
    assert KEY not in caplog.text and SECRET_BODY not in caplog.text
    assert KEY not in json.dumps(r.doc) and SECRET_BODY not in json.dumps(r.doc, ensure_ascii=False)
    assert KEY not in r.report.summary() and SECRET_BODY not in r.report.summary()


def test_report_summary_lists_every_counter(members, index):
    r = run(doc(), [notice(1)], FakePost(events_reply(ev())), members, index)
    s = r.report.summary()
    for part in ("대상 1개", "events 1", "none 0", "no_text 0", "error 0", "보류 0", "새 일정 1개", "중복 제외 0", "API 호출 1회", MODEL):
        assert part in s, part
