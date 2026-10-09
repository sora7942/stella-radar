"""site/index.html의 '순수 로직 구역'(`/* <logic> … /* </logic> */`)을 node로 실행해 시험한다 (node가 없으면 건너뜀).
구역은 DOM 없이 M(멤버)·G(그룹)만 바깥에서 받는다. 화면(칩·배지·썸네일·콘솔 에러)은 브라우저로 따로 확인한다.
기준 모델은 JS와 따로 파이썬으로 썼다 — SPEC v1.1 2-2의 문장(분류 × 그룹·멤버 AND, 쇼츠 숨김)에서 출발한다."""
import itertools
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node가 없어 index.html 로직 시험을 건너뜀")
HTML = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
MEMBERS = json.loads((ROOT / "site" / "data" / "members.json").read_text(encoding="utf-8"))


def zone() -> str:
    found = re.findall(r"/\* <logic>[^\n]*\n(.*?)/\* </logic> \*/", HTML, re.S)
    assert len(found) == 1, "순수 로직 구역 표시(<logic>)가 정확히 한 번 있어야 한다"
    return found[0]


HARNESS = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const M = input.M, G = input.G;
const mem = {};
if (input.ls === 'works') globalThis.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
else if (input.ls === 'throws') globalThis.localStorage = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); } };
// input.ls === 'missing' → localStorage 자체가 없다 (접근하면 ReferenceError)
__ZONE__
const fns = { membersOf, expand, esc, matchCat, matchGroup, isShort, shortHref, feedFilter, loadHideShorts, saveHideShorts, CATS: () => CATS,
  kstDay, timeOf, normTitle, safeHref, normEvent, mergeEvents, visibleEvents, autoChip, loadShowGoods, saveShowGoods };
console.log(JSON.stringify(input.calls.map(c => fns[c.fn](...c.args))));
"""


def js(calls: list[tuple], ls: str = "works") -> list:
    m = {k: {"n": v["n"], "g": v["g"]} for k, v in MEMBERS["members"].items()}
    payload = json.dumps({"M": m, "G": MEMBERS["groups"], "ls": ls, "calls": [{"fn": c[0], "args": list(c[1:])} for c in calls]}, ensure_ascii=False)
    r = subprocess.run([NODE, "-e", HARNESS.replace("__ZONE__", zone())], input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr[:600]
    return json.loads(r.stdout)


def one(*call, ls="works"):
    return js([call], ls)[0]


# ============================ 시험용 소식 항목 ===================================
def it(id_, cat, who, **kw):
    return {"id": id_, "cat": cat, "who": who, "title": id_, "url": f"https://example.invalid/{id_}", **kw}


ITEMS = [
    it("yt-A", "영상", ["lize"], yt="A", short=True),        # 리제의 쇼츠
    it("yt-B", "영상", ["lize"], yt="B", short=False),       # 리제의 일반 영상
    it("yt-C", "영상", ["lize"], yt="C"),                    # 아직 판별 전(필드 없음) → 일반 취급
    it("yt-D", "영상", ["kangji"], yt="D", short=True),      # 강지의 쇼츠
    it("sl-E", "공지", ["all"]),
    it("sl-F", "이벤트", ["everys"]),
    it("sl-G", "굿즈", ["hina"]),
    it("mu-H", "음악", ["riko"], yt="H"),                    # 음악 항목도 yt가 있지만 short는 없다
    it("yt-I", "영상", ["universe"], yt="I", short=True),    # 그룹 태그가 붙은 쇼츠
    it("yt-J", "영상", ["all"], yt="J", short=False),        # 공식 채널 영상(단체)
]
GROUPS = ["all-view", "boss", "everys", "universe", "cliche", "all"]
KEYS = list(MEMBERS["members"])


def model(item, g, m, c, hide):
    """SPEC v1.1 2-2의 문장에서 따로 쓴 기준 모델."""
    members = MEMBERS["members"]
    if hide and item.get("short") is True:
        return False
    cats = {"video": {"영상"}, "notice": {"공지", "이벤트"}, "goods": {"굿즈"}, "music": {"음악"}}.get(c)  # 'all'·알 수 없는 키는 제한 없음
    if cats is not None and item["cat"] not in cats:
        return False
    who = item.get("who", [])
    if m:  # 멤버 필터: 멤버 태그, 그룹 태그(그 그룹의 멤버 전원), all(강지를 뺀 전원)
        expanded = set()
        for w in who:
            if w in members:
                expanded.add(w)
            elif w == "all":
                expanded |= {k for k in members if k != "kangji"}
            else:
                expanded |= {k for k, v in members.items() if v["g"] == w}
        return m in expanded
    if g == "all-view":
        return True
    if g == "all":
        return "all" in who
    if g == "boss":
        return "kangji" in who
    in_group = {k for k, v in members.items() if v["g"] == g}
    return g in who or any(w in in_group for w in who)


# ============================ 분류 × 그룹 × 멤버 × 쇼츠 숨김 ======================
def test_every_combination_matches_the_reference_model():
    combos = list(itertools.product(["all", "video", "notice", "goods", "music"], GROUPS, [None] + KEYS, [False, True]))
    calls = [("feedFilter", item, {"c": c, "g": g, "m": m, "hideShorts": hide}) for c, g, m, hide in combos for item in ITEMS]
    got = js(calls)
    want = [model(item, g, m, c, hide) for c, g, m, hide in combos for item in ITEMS]
    bad = [(calls[i][1]["id"], calls[i][2]) for i in range(len(calls)) if got[i] != want[i]]
    assert bad == [] and len(calls) > 6000


def ids(c="all", g="all-view", m=None, hide=False):
    got = js([("feedFilter", item, {"c": c, "g": g, "m": m, "hideShorts": hide}) for item in ITEMS])
    return [item["id"] for item, ok in zip(ITEMS, got) if ok]


def test_category_chips_follow_the_spec():
    assert ids("all") == [i["id"] for i in ITEMS]
    assert ids("video") == ["yt-A", "yt-B", "yt-C", "yt-D", "yt-I", "yt-J"]
    assert ids("notice") == ["sl-E", "sl-F"]  # 공지/이벤트 = 공지 + 이벤트
    assert ids("goods") == ["sl-G"] and ids("music") == ["mu-H"]


def test_hide_shorts_removes_only_items_known_to_be_shorts():
    assert ids(hide=True) == ["yt-B", "yt-C", "sl-E", "sl-F", "sl-G", "mu-H", "yt-J"]  # A·D·I(short:true)만 빠진다. 필드 없음(C)·false(B,J)는 남는다
    assert ids("video", hide=True) == ["yt-B", "yt-C", "yt-J"]


def test_category_and_group_and_hide_are_anded():
    assert ids("video", "universe") == ["yt-A", "yt-B", "yt-C", "yt-I"]  # 리제(유니버스)·유니버스 태그. 단체·강지·에버리스는 제외
    assert ids("video", "universe", hide=True) == ["yt-B", "yt-C"]
    assert ids("notice", "everys") == ["sl-F"] and ids("goods", "everys") == []  # 히나는 유니버스라 에버리스 굿즈에는 없다
    assert ids("goods", "universe") == ["sl-G"] and ids("goods", "cliche") == []
    assert ids("music", "universe") == [] and ids("video", "boss") == ["yt-D"] and ids("video", "boss", hide=True) == []


def test_a_member_filter_overrides_the_group_chip_and_still_honors_category_and_hide():
    assert ids("video", "universe", "lize") == ["yt-A", "yt-B", "yt-C", "yt-I", "yt-J"]  # 'all' 태그는 강지를 뺀 전원으로 펼쳐진다
    assert ids("video", "universe", "lize", hide=True) == ["yt-B", "yt-C", "yt-J"]
    assert ids("video", "all-view", "kangji") == ["yt-D"]  # 단체(all)에는 강지가 들어 있지 않다


def test_an_unknown_category_key_means_everything():
    assert ids("zzz") == ids("all")


def test_categories_are_the_five_chips_in_order():
    cats = one("CATS")
    assert [c["label"] for c in cats] == ["전체", "영상", "공지/이벤트", "굿즈", "음악"]
    assert [c["k"] for c in cats] == ["all", "video", "notice", "goods", "music"]
    assert [c["cats"] for c in cats] == [None, ["영상"], ["공지", "이벤트"], ["굿즈"], ["음악"]]


# ============================ 쇼츠 판정과 링크 ==================================
@pytest.mark.parametrize("value, expected", [(True, True), (False, False), (None, False), ("true", False), (1, False), (0, False)])
def test_only_a_literal_true_counts_as_a_short(value, expected):
    assert one("isShort", {"id": "yt-x", "short": value}) is expected


def test_a_missing_short_field_means_not_a_short():
    assert one("isShort", {"id": "yt-x"}) is False and one("isShort", None) is False


def test_short_link_goes_to_the_shorts_url_and_everything_else_keeps_the_original_url():
    base = {"url": "https://www.youtube.com/watch?v=VID", "yt": "VID"}
    assert one("shortHref", {**base, "short": True}) == "https://www.youtube.com/shorts/VID"
    assert one("shortHref", {**base, "short": False}) == base["url"]
    assert one("shortHref", base) == base["url"]  # 미정
    assert one("shortHref", {"url": "https://stellive.me/music/1", "yt": "VID"}) == "https://stellive.me/music/1"  # 음악 항목
    assert one("shortHref", {"url": "https://u", "short": True}) == "https://u"  # videoId가 없으면 만들 수 없다


def test_short_link_encodes_the_video_id():
    assert one("shortHref", {"url": "u", "yt": "a b/c?d", "short": True}) == "https://www.youtube.com/shorts/a%20b%2Fc%3Fd"


def test_esc_escapes_markup_characters():
    assert one("esc", "<img src=x onerror=\"a('b')\">&") == "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;" and one("esc", None) == ""


# ============================ localStorage: 실패해도 동작 ========================
def test_hide_shorts_defaults_to_showing_and_round_trips():
    got = js([("loadHideShorts",), ("saveHideShorts", True), ("loadHideShorts",), ("saveHideShorts", False), ("loadHideShorts",)])
    assert got == [False, None, True, None, False]


@pytest.mark.parametrize("ls", ["throws", "missing"])
def test_storage_failures_never_break_loading_or_saving(ls):
    got = js([("loadHideShorts",), ("saveHideShorts", True), ("loadHideShorts",)], ls=ls)
    assert got == [False, None, False]  # 읽기는 '보이기'(기본값), 쓰기는 조용히 무시. 예외가 올라오지 않는다 (올라오면 node가 실패한다)


def test_a_garbage_stored_value_means_show():
    m = {k: {"n": "x", "g": "g"} for k in KEYS}  # 보관된 값이 '1'이 아니면 기본값(보이기)
    harness = HARNESS.replace("__ZONE__", zone()).replace("const mem = {};", "const mem = {sr_hideShorts: 'yes'};")
    r = subprocess.run([NODE, "-e", harness], input=json.dumps({"M": m, "G": [], "ls": "works", "calls": [{"fn": "loadHideShorts", "args": []}]}), capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == [False]


# ============================ 일정: 수동 + 자동 합치기 (기능 3) ===================
MANUAL = json.loads((ROOT / "site" / "data" / "events.json").read_text(encoding="utf-8"))["items"]  # 실제 수동 일정: ev-popup-rsv, ev-popup
NOTICE = "https://stellive.me/news/13905"


def auto(kind="popup", title="STELLA MODE:ON 팝업스토어", start="2026-10-23", **kw):
    return {"id": f"auto-{kind}-{start}", "source": "sl-13905", "kind": kind, "title": title, "start": start, "who": ["all"], "url": NOTICE, **kw}


def merged_ids(manual, autos):
    return [e["id"] for e in one("mergeEvents", manual, autos)]


def test_kst_day_reads_dates_and_instants_as_korean_calendar_days():
    from datetime import datetime, timezone
    day = lambda y, m, d: int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)  # noqa: E731
    got = js([("kstDay", "2026-10-23"), ("kstDay", "2026-10-12T20:00:00+09:00"), ("kstDay", "2026-10-11T16:00:00Z"), ("kstDay", "2026-10-11T14:59:59Z"), ("kstDay", "내일")])
    assert got[:4] == [day(2026, 10, 23), day(2026, 10, 12), day(2026, 10, 12), day(2026, 10, 11)] and got[4] is None  # NaN은 JSON에서 null


def test_time_of_gives_the_korean_clock_time_only_for_instants():
    got = js([("timeOf", "2026-10-12T20:00:00+09:00"), ("timeOf", "2026-10-12T11:05:00Z"), ("timeOf", "2026-10-12"), ("timeOf", "엉터리 시각입니다"), ("timeOf", None)])
    assert got == ["20:00", "20:05", "", "", ""]


@pytest.mark.parametrize("text,expected", [
    ("<STELLA MODE:ON> 팝업스토어!", "stellamodeon팝업스토어"), ("STELLA  MODE:ON", "stellamodeon"), ("ＳＴＥＬＬＡ １", "stella1"), ("『!!!』", ""), ("", ""), (None, ""),
])
def test_norm_title_drops_spaces_and_symbols_like_the_server(text, expected):
    assert one("normTitle", text) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://stellive.me/news/1", "https://stellive.me/news/1"), ("http://x.test/a", "http://x.test/a"), ("HTTPS://X.TEST", "HTTPS://X.TEST"),
    ("javascript:alert(1)", ""), ("data:text/html,x", ""), ("//evil.test", ""), ("ftp://x", ""), ("", ""), (None, ""), (5, ""),
])
def test_safe_href_allows_only_http_and_https(url, expected):
    assert one("safeHref", url) == expected


def test_a_manual_event_keeps_its_note_and_is_an_event():
    e = one("normEvent", {"id": "m", "title": "팝업", "start": "2026-10-23", "end": "2026-11-01", "who": ["all"], "note": "서울 · 10:00–20:00", "url": "https://x.test/a"}, False)
    assert (e["kind"], e["auto"], e["note"], e["end"], e["url"]) == ("이벤트", False, "서울 · 10:00–20:00", "2026-11-01", "https://x.test/a")


def test_an_auto_event_builds_its_note_from_time_and_place_and_goods_becomes_goods():
    e = one("normEvent", auto("popup", end="2026-11-01", time="10:00–20:00", place="서울 광진구"), True)
    assert (e["kind"], e["auto"], e["note"]) == ("이벤트", True, "10:00–20:00 · 서울 광진구")
    assert one("normEvent", auto("goods", "타비 굿즈 판매 마감", "2026-10-07", time="23:59"), True)["kind"] == "굿즈"
    for k in ("concert", "reservation", "broadcast", "other"):
        assert one("normEvent", auto(k), True)["kind"] == "이벤트"  # goods만 따로 보인다
    assert one("normEvent", auto("goods"), False)["kind"] == "이벤트"  # 수동 일정은 kind를 보지 않는다


def test_a_timed_start_shows_its_clock_time_and_hides_the_redundant_time_field():
    e = one("normEvent", auto("reservation", "예약 오픈", "2026-10-12T20:00:00+09:00", time="20시"), True)
    assert e["tm"] == "20:00" and e["note"] == ""


@pytest.mark.parametrize("bad", [None, "문자열", {}, {"title": "t"}, {"start": "2026-10-23"}, {"title": "", "start": "2026-10-23"}, {"title": 5, "start": "2026-10-23"},
                                  {"title": "t", "start": 20261023}, {"title": "t", "start": "내일"}, {"title": "t", "start": "2026-10-23", "end": "엉터리"},
                                  {"title": "t", "start": "2026-10-23", "end": "2026-10-22"}])
def test_unreadable_events_are_skipped_instead_of_breaking_the_calendar(bad):
    assert one("normEvent", bad, True) is None and one("mergeEvents", [bad], [bad]) == []


def test_missing_who_means_everyone_and_an_unsafe_url_is_dropped():
    e = one("normEvent", {"title": "t", "start": "2026-10-23", "url": "javascript:alert(1)"}, True)
    assert e["who"] == ["all"] and e["url"] == ""


def test_manual_events_come_first_and_unrelated_auto_events_are_added():
    got = merged_ids(MANUAL, [auto("concert", "리제 콘서트", "2026-12-01", id="auto-x")])
    assert got == ["ev-popup-rsv", "ev-popup", "auto-x"]
    assert one("mergeEvents", None, None) == [] and merged_ids([], [auto(id="only-auto")]) == ["only-auto"]


def test_the_real_popup_event_hides_its_auto_twin_by_start_day_and_same_url():
    """수동 ev-popup(2026-10-23~11-01, url=13905)과 13905에서 뽑은 팝업은 같은 시작일 + 같은 url이라 수동만 남는다."""
    assert "ev-popup" in {m["id"] for m in MANUAL} and next(m for m in MANUAL if m["id"] == "ev-popup")["url"] == NOTICE
    assert merged_ids(MANUAL, [auto("popup", "STELLA MODE:ON 팝업스토어", "2026-10-23", end="2026-11-01", id="a")]) == ["ev-popup-rsv", "ev-popup"]
    assert merged_ids(MANUAL, [auto("popup", "무관한 제목", "2026-10-23", end="2026-11-01", id="a", url=NOTICE)]) == ["ev-popup-rsv", "ev-popup"]  # 제목이 달라도 같은 url + 같은 end


def test_a_title_that_contains_the_other_hides_the_auto_event_when_the_start_day_matches():
    manual = [{"id": "m", "title": "2026 STELLIVE POP-UP STELLA MODE:ON", "start": "2026-10-23", "who": ["all"], "url": "https://other.test/x"}]
    assert merged_ids(manual, [auto(title="STELLA MODE:ON", id="a")]) == ["m"]  # 자동 제목이 수동 제목에 들어 있다
    assert merged_ids(manual, [auto(title="[2026 STELLIVE POP-UP STELLA MODE:ON] 팝업 안내", id="a")]) == ["m"]  # 수동 제목이 자동 제목에 들어 있다
    assert merged_ids(manual, [auto(title="완전히 다른 행사", id="a")]) == ["m", "a"]


def test_a_different_start_day_is_never_compared_even_with_the_same_url_and_title():
    manual = [{"id": "m", "title": "팝업스토어", "start": "2026-10-23", "who": ["all"], "url": NOTICE}]
    assert merged_ids(manual, [auto(title="팝업스토어", start="2026-10-24", id="a")]) == ["m", "a"]
    assert merged_ids(manual, [auto(title="팝업스토어", start="2026-10-23T10:00:00+09:00", id="b")]) == ["m"]  # 같은 날(시각 포함)은 같은 시작일이다


def test_the_start_day_is_the_korean_day_not_the_utc_day():
    manual = [{"id": "m", "title": "예약 오픈", "start": "2026-10-12T00:30:00+09:00", "who": ["all"]}]  # UTC로는 10-11
    assert merged_ids(manual, [auto("reservation", "예약 오픈", "2026-10-12", id="a")]) == ["m"]


def test_a_separate_event_from_the_same_notice_and_start_day_stays_when_its_end_differs():
    """url 일치는 end도 같을 때만 중복이다 (사용자 수정 2026-10-09). 자동 일정의 url은 항상 출처 공지 URL이라, end를 안 보면 수동 ev-popup(url=13905)과 같은 날
    시작하는 13905의 별건 일정(포토이즘 10/23~11/05, kind other)까지 걸려 숨겨졌다."""
    photoism = auto("other", "PHOTOISM X STELLA MODE:ON 콜라보 프레임", "2026-10-23", end="2026-11-05", id="photo")
    assert merged_ids(MANUAL, [photoism]) == ["ev-popup-rsv", "ev-popup", "photo"]  # 11/05 ≠ 11/01 → 남는다
    assert merged_ids(MANUAL, [{**photoism, "end": "2026-11-01"}]) == ["ev-popup-rsv", "ev-popup"]  # 끝나는 날이 같으면(= 같은 팝업) 걸러진다
    assert merged_ids(MANUAL, [{k: v for k, v in photoism.items() if k != "end"}]) == ["ev-popup-rsv", "ev-popup", "photo"]  # 하루짜리(end 없음)도 다르다
    assert merged_ids(MANUAL, [{**photoism, "start": "2026-10-24"}]) == ["ev-popup-rsv", "ev-popup", "photo"]


def test_the_end_condition_applies_only_to_the_url_path_not_to_title_containment():
    manual = [{"id": "m", "title": "2026 STELLIVE POP-UP STELLA MODE:ON", "start": "2026-10-23", "end": "2026-11-01", "who": ["all"], "url": "https://other.test/x"}]
    assert merged_ids(manual, [auto(title="STELLA MODE:ON", end="2026-11-05", id="a")]) == ["m"]  # 제목 포함이면 end가 달라도 걸러진다 (합의한 규칙 그대로)


def test_same_url_with_no_end_on_both_sides_is_filtered():
    """둘 다 end가 없으면(하루짜리) end도 같다. 날짜만 있는 수동 일정이 공지 url을 달고 있으면 같은 날 자동 일정은 걸러진다 (시각 규칙과 무관하게 url + end 경로)."""
    manual = [{"id": "m", "title": "예약 안내", "start": "2026-10-12", "who": ["all"], "url": NOTICE}]
    assert merged_ids(manual, [auto("reservation", "무관한 제목", "2026-10-12", id="a")]) == ["m"]
    assert merged_ids(manual, [auto("reservation", "무관한 제목", "2026-10-12", end="2026-10-12", id="a")]) == ["m"]  # end가 start와 같은 날이면 같은 값이다
    assert merged_ids(manual, [auto("reservation", "무관한 제목", "2026-10-12", end="2026-10-13", id="a")]) == ["m", "a"]


def test_the_real_reservation_event_hides_its_auto_twin_by_the_identical_start_time():
    """실제 수동 ev-popup-rsv(url=naver.me, 시작 2026-10-12 20:00)는 url·제목이 달라도, 둘 다 시각이 있는 start가 완전히 같으므로 자동 예약 오픈이 걸러진다 (사용자 결정 2026-10-09).
    3-2의 실제 추출 결과 '2026-10-12T20:00:00+09:00'(제목 'STELLA MODE:ON 팝업스토어 사전 예약 오픈', url=13962)가 그 사례다."""
    rsv = next(m for m in MANUAL if m["id"] == "ev-popup-rsv")
    assert "end" not in rsv and rsv["url"] != NOTICE and len(rsv["start"]) > 10
    real = auto("reservation", "STELLA MODE:ON 팝업스토어 사전 예약 오픈", "2026-10-12T20:00:00+09:00", id="a", url="https://stellive.me/news/13962")
    assert merged_ids(MANUAL, [real]) == ["ev-popup-rsv", "ev-popup"]
    assert merged_ids(MANUAL, [{**real, "title": "전혀 다른 제목", "url": ""}]) == ["ev-popup-rsv", "ev-popup"]  # 제목·url과 무관
    assert merged_ids(MANUAL, [{**real, "start": "2026-10-12T11:00:00Z"}]) == ["ev-popup-rsv", "ev-popup"]  # 같은 시각(UTC 표기)도 같은 start
    assert merged_ids(MANUAL, [{**real, "kind": "other"}]) == ["ev-popup-rsv", "ev-popup"]  # kind와도 무관


def test_the_time_rule_needs_the_exact_same_instant_and_never_applies_to_date_only_events():
    rsv = [next(m for m in MANUAL if m["id"] == "ev-popup-rsv")]
    mk = lambda start, kind="reservation": auto(kind, "무관한 제목", start, id="a", url="https://stellive.me/news/1")  # noqa: E731
    assert merged_ids(rsv, [mk("2026-10-12T20:01:00+09:00")]) == ["ev-popup-rsv", "a"]  # 1분만 달라도 다른 일정
    assert merged_ids(rsv, [mk("2026-10-12T19:00:00+09:00")]) == ["ev-popup-rsv", "a"]
    assert merged_ids(rsv, [mk("2026-10-12")]) == ["ev-popup-rsv", "a"]  # 같은 날이라도 날짜만 있는 자동 일정은 걸리지 않는다
    assert merged_ids(rsv, [mk("2026-10-13T20:00:00+09:00")]) == ["ev-popup-rsv", "a"]  # 다른 날 같은 시각
    dateonly = [{"id": "m", "title": "수동 일정", "start": "2026-10-12", "who": ["all"], "url": "https://x.test/m"}]
    assert merged_ids(dateonly, [mk("2026-10-12T20:00:00+09:00")]) == ["m", "a"]  # 수동이 날짜만이면 시각 규칙 대상이 아니다
    assert merged_ids(dateonly, [mk("2026-10-12")]) == ["m", "a"]  # 둘 다 날짜만 있는 같은 날의 서로 다른 일정은 걸리지 않는다
    assert merged_ids(dateonly, [mk("2026-10-12", kind="goods")]) == ["m", "a"]


def test_auto_events_are_not_deduplicated_against_each_other_on_the_site():
    """자동끼리의 중복 제거는 저장 시점(서버)에서 끝난다. 사이트는 받은 자동 일정을 그대로 보여준다."""
    assert merged_ids([], [auto(id="a"), auto(id="b")]) == ["a", "b"]


def test_manual_vs_auto_merge_matches_an_independent_reference_model():
    import unicodedata
    norm = lambda t: "".join(c for c in unicodedata.normalize("NFKC", t).casefold() if c.isalnum())  # noqa: E731
    urls, titles, days, ends = ([None, "https://a.test/1", "https://a.test/2"], ["팝업스토어", "STELLA MODE:ON 팝업스토어 안내", "무관한 일정", "!!!"],
                                ["2026-10-23", "2026-10-24", "2026-10-23T20:00:00+09:00"], [None, "2026-11-01"])
    specs = [(u, t, d, e) for u in urls for t in titles for d in days for e in ends]
    calls, want = [], []
    for mu, mt, md, me in specs:
        m = {"id": "m", "title": mt, "start": md, "who": ["all"], **({"url": mu} if mu else {}), **({"end": me} if me else {})}
        for au, at, ad, ae in specs:
            a = {"id": "a", "title": at, "start": ad, "kind": "popup", "who": ["all"], **({"url": au} if au else {}), **({"end": ae} if ae else {})}
            calls.append(("mergeEvents", [m], [a]))
            same_day = ad[:10] == md[:10]
            same_url = mu is not None and mu == au and (me or md[:10]) == (ae or ad[:10])  # url 일치는 끝나는 날(없으면 시작일)도 같을 때만
            same_title = norm(at) != "" and norm(mt) != "" and (norm(at) in norm(mt) or norm(mt) in norm(at))
            same_instant = len(ad) > 10 and len(md) > 10 and ad == md  # 둘 다 시각이 있고 start가 완전히 같다 (표기가 모두 +09:00라 문자열 비교 = 시각 비교)
            want.append(["m"] if same_day and (same_url or same_title or same_instant) else ["m", "a"])
    got = [[e["id"] for e in r] for r in js(calls)]
    bad = [(calls[i][1][0], calls[i][2][0]) for i in range(len(calls)) if got[i] != want[i]]
    assert bad == [] and len(calls) == len(specs) ** 2 == 5184


def test_goods_toggle_hides_only_goods_and_keeps_everything_else():
    evs = one("mergeEvents", MANUAL, [auto("goods", "타비 굿즈 판매 마감", "2026-10-07", id="g"), auto("popup", "다른 팝업", "2026-11-20", id="p"), auto("other", "콜라보", "2026-11-21", id="o")])
    shown = lambda on: [e["id"] for e in one("visibleEvents", evs, on)]  # noqa: E731
    assert shown(True) == ["ev-popup-rsv", "ev-popup", "g", "p", "o"]
    assert shown(False) == ["ev-popup-rsv", "ev-popup", "p", "o"]


def test_the_auto_chip_is_only_for_auto_events_and_links_to_the_original_notice():
    manual = one("normEvent", MANUAL[1], False)
    assert one("autoChip", manual) == "" and one("autoChip", None) == ""
    chip = one("autoChip", one("normEvent", auto(), True))
    assert chip.startswith(f'<a class="autob" href="{NOTICE}" target="_blank" rel="noopener"') and chip.endswith("자동 · 원문</a>")
    nolink = one("autoChip", one("normEvent", auto(url=""), True))
    assert nolink.startswith('<span class="autob"') and "href" not in nolink and nolink.endswith(">자동</span>")


def test_the_chip_never_carries_the_title_and_escapes_the_url():
    e = one("normEvent", auto(title="<img src=x onerror=alert(1)>", url='https://x.test/a"onmouseover="alert(1)'), True)
    chip = one("autoChip", e)
    assert "<img" not in chip and 'href="https://x.test/a&quot;onmouseover=&quot;alert(1)"' in chip and 'onmouseover="' not in chip


def test_show_goods_defaults_to_on_and_round_trips():
    got = js([("loadShowGoods",), ("saveShowGoods", False), ("loadShowGoods",), ("saveShowGoods", True), ("loadShowGoods",)])
    assert got == [True, None, False, None, True]


@pytest.mark.parametrize("ls", ["throws", "missing"])
def test_show_goods_storage_failures_leave_the_default_and_never_throw(ls):
    assert js([("loadShowGoods",), ("saveShowGoods", False), ("loadShowGoods",)], ls=ls) == [True, None, True]


def test_a_garbage_stored_show_goods_value_means_on():
    harness = HARNESS.replace("__ZONE__", zone()).replace("const mem = {};", "const mem = {sr_showGoods: 'maybe'};")
    r = subprocess.run([NODE, "-e", harness], input=json.dumps({"M": {}, "G": [], "ls": "works", "calls": [{"fn": "loadShowGoods", "args": []}]}), capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == [True]


# ============================ index.html 구조 ===================================
def test_the_logic_zone_is_dom_free():
    z = zone()
    for forbidden in ("document", "window.", "querySelector", "$(", "innerHTML", "addEventListener", "getElementById", "fetch("):
        assert forbidden not in z, f"순수 로직 구역에 DOM 접근이 있다: {forbidden}"


def test_localstorage_is_only_touched_inside_the_try_catch_wrapper():
    assert [l for l in HTML.splitlines() if "localStorage" in l and "var store=" not in l and not l.lstrip().startswith(("//", "/*"))] == []
    store_line = next(l for l in HTML.splitlines() if l.startswith("var store="))
    assert store_line.count("try{") == 2 and store_line.count("catch(e)") == 2  # 읽기·쓰기 둘 다


def test_the_category_chip_row_sits_above_the_group_chips_and_the_toggle_is_rendered_with_it():
    assert HTML.index('id="cchips"') < HTML.index('id="gchips"') < HTML.index('id="mchips"')
    assert 'id="hideshorts"' in HTML and "쇼츠 숨기기" in HTML and 'aria-pressed="\'+hideShorts+\'"' in HTML


def test_feed_cards_link_both_thumbnail_and_title_through_the_short_aware_href():
    body = HTML[HTML.index("function renderFeed()"):HTML.index("// ---------- 일정 ----------")]
    assert "esc(it.url)" not in body and body.count("esc(href)") == 2 and "shortHref(it)" in body
    assert "shortb" in body and "' vert'" in body  # 배지와 세로 썸네일 클래스


def test_the_old_global_match_filter_is_gone():
    assert "function match(" not in HTML and ".filter(match)" not in HTML


def test_new_styles_use_theme_tokens_only():
    css = re.findall(r"\.(?:shortb|chip\.toggle|fthumb\.vert(?: img)?)\{[^}]*\}", HTML)
    assert len(css) == 4  # .fthumb.vert, .fthumb.vert img, .shortb, .chip.toggle
    for rule in css:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", rule), f"하드코딩된 색: {rule}"
    assert "var(--hot)" in "".join(css) and "var(--hot-soft)" in "".join(css)  # 라이트·다크 모두 --hot 계열 토큰


def test_the_vertical_thumbnail_box_is_nine_by_sixteen_and_cropped_not_stretched():
    rules = " ".join(re.findall(r"\.fthumb\.vert[^{]*\{[^}]*\}", HTML))
    assert "aspect-ratio:9/16" in rules and "object-fit:cover" in rules and "max-width:none" in rules


# ============================ 일정 화면 구조 (기능 3) ===============================
def test_the_goods_toggle_exists_above_the_calendar_and_in_the_upcoming_panel_and_both_share_one_state():
    assert 'id="showgoods"' in HTML and 'id="showgoods-up"' in HTML
    assert HTML.index('id="v-grid"') < HTML.index('id="showgoods"') < HTML.index('id="mnav"')  # 달력 위 막대: 보기 방식 · 굿즈 토글 · 월 이동
    assert HTML.index('id="showgoods-up"') < HTML.index('id="upnext"')  # 소식 탭의 패널 머리
    assert 'showGoods=v;saveShowGoods(v);syncGoods();renderUpcoming();' in HTML and HTML.count('["#showgoods","#showgoods-up"]') == 2


def test_every_event_view_goes_through_the_same_filtered_list():
    """달력 그리드·목록·다가오는 일정 패널·'다음:' 문구는 모두 evList()(= 병합 + 굿즈 토글)에서 나온다."""
    assert "function evList(){return visibleEvents(mergeEvents(DATA.events,DATA.auto),showGoods);}" in HTML
    body = HTML[HTML.index("function eventsOn("):HTML.index("function linked(")]
    assert body.count("evList()") == 2 and "DATA.events" not in body  # eventsOn(그리드·일별 목록) + allEvents(패널·다음·월별 목록)
    assert HTML.count("+autoChip(e)+") == 3  # 사용처: 다가오는 일정 패널·목록 보기·일별 목록 (함수 정의는 따로)


def test_auto_events_are_loaded_but_a_failure_cannot_break_the_page():
    line = next(l for l in HTML.splitlines() if 'getJSON("data/auto_events.json")' in l)
    assert line.rstrip().endswith("// 없거나 실패해도 수동 일정만으로 동작한다") or ".catch(function(){})" in line


def test_the_new_event_styles_use_theme_tokens_only():
    css = re.findall(r"(?:\.autob|a\.autob:hover|\.pill\.goods|\.ekind\.goods|\.chip\.sm|\.panel h3\.hd|#showgoods)(?:[^{]*)\{[^}]*\}", HTML)
    assert len(css) >= 7
    for rule in css:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", rule), f"하드코딩된 색: {rule}"
    assert "var(--sunk)" in "".join(css) and "var(--muted)" in "".join(css)


def test_event_titles_and_places_are_always_escaped_before_going_into_innerhtml():
    body = HTML[HTML.index("function eventsOn("):HTML.index("function moveMonth(")]
    assert "innerHTML" in body
    assert "+e.title+" not in body and "+e.note+" not in body and "+e.place+" not in body  # 날것으로 이어 붙이지 않는다
