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
const fns = { membersOf, expand, esc, matchCat, matchGroup, isShort, shortHref, feedFilter, loadHideShorts, saveHideShorts, CATS: () => CATS };
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
