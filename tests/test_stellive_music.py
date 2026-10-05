"""공식 음악 소스: 파서(실제 픽스처) + 분류 판정(가짜 사이트).

사용자 요청 2가지가 여기 있다:
  ① ALBUM/EP/SINGLE/OTHERS 탭은 페이지가 여러 개여도 끝까지 읽는다 (TestReadTabToTheEnd)
  ② 계산한 COVER 개수와 COVER 탭 라벨([252])이 다르면, 그리고 처음 보는 분류 탭이 생기면 경고한다 (TestWarnings)
"""
import logging
import math
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from conftest import FIXTURES, make_response
from fakesite import CIDS, Site, song, tab_url
from updater import config, tagging
from updater.sources import stellive_music as sm
from updater.sources.stellive_music import DetailParseError, ListParseError, TabReadError

LOG = "updater.sources.stellive_music"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=config.KST)


@pytest.fixture(scope="module")
def index(members):
    return tagging.build_index(members)


def fixture(name):
    return (FIXTURES / name).read_bytes()


# ============================================================================
# 실제 응답 픽스처
# ============================================================================
@pytest.fixture(scope="module")
def page():
    return sm.parse_list(fixture("stellive_music_list.html"))


class TestParseListFixture:
    def test_items(self, page):
        assert len(page.items) == 29
        first = page.items[0]
        assert (first.id, first.title, first.artist) == ("13638", "물떼새(千鳥)『ヨルシカ』Cover", "Arahashi Tabi")

    def test_total_is_the_site_count_not_the_trimmed_fixture_count(self, page):
        assert page.total == 286  # '총 286건' (픽스처는 29건만 남긴 것)

    def test_tabs_with_label_counts(self, page):
        assert [(t.name, t.href, t.count) for t in page.tabs] == [
            ("ALL", "/music", None),
            ("ALBUM", "/music/category/277", None),  # 빈 탭은 라벨 숫자가 없다
            ("EP", "/music/category/8591", 7),
            ("SINGLE", "/music/category/278", 19),
            ("COVER", "/music/category/279", 252),
            ("OTHERS", "/music/category/555", 8),
        ]

    def test_artists_include_groups_and_external(self, page):
        artists = {i.artist for i in page.items}
        assert {"Everys", "Cliche", "STELLIVE", "Hanako Nana x Todoroki Hajime"} <= artists

    @pytest.mark.parametrize("content", [b"", b"<html>blocked</html>", b'<div id="board_list"><div class="gallery_wrap"></div></div>'])
    def test_no_items_is_an_error(self, content):
        with pytest.raises(ListParseError):
            sm.parse_list(content)


class TestParseDetailFixture:
    def test_cover(self):
        d = sm.parse_detail(fixture("stellive_music_detail_cover_13638.html"))
        assert d == sm.Detail(
            title="물떼새(千鳥)『ヨルシカ』Cover",
            artist="Arahashi Tabi",  # 끝의 &nbsp; 제거
            date="2026-09-07",
            yt="uBtFoUXR9Qc",
            leaf="아라하시 타비",  # 상세의 분류는 하위 분류(멤버 이름) — COVER가 아니다
        )

    def test_ep(self):
        d = sm.parse_detail(fixture("stellive_music_detail_ep_12876.html"))
        assert d.title == "악당주의보『STELLIVE Cliché 1st EP 「Colorful Strokes」』"
        assert (d.artist, d.date, d.yt, d.leaf) == ("Yuzuha Riko", "2026-07-24", "P_oxx3_VpIY", "EP")

    def test_not_a_detail_page(self):
        with pytest.raises(DetailParseError):
            sm.parse_detail(b"<html>blocked</html>")

    def test_missing_date_or_title_is_an_error(self):
        no_date = b'<div class="content_header"><h1><a>t</a></h1></div><table class="extra"><tr><th>x</th><td>y</td></tr></table>'
        no_title = '<div class="content_header"></div><table class="extra"><tr><th>날짜</th><td>2026.01.02</td></tr></table>'.encode("utf-8")
        for content in (no_date, no_title):
            with pytest.raises(DetailParseError):
                sm.parse_detail(content)

    def test_missing_artist_and_video_are_tolerated(self):
        html = '<div class="content_header"><h1><a>곡</a></h1></div><table class="extra"><tr><th>날짜</th><td>2026.01.02</td></tr></table>'
        d = sm.parse_detail(html.encode("utf-8"))
        assert d.artist is None and d.yt is None and d.date == "2026-01-02"


class TestParseTabPageFixture:
    def test_single_page_tab(self):
        ids, links = sm.parse_tab_page(fixture("stellive_music_category_ep.html"), "https://stellive.me/music/category/8591")
        assert ids == ["12882", "12881", "12879", "12876", "11838", "11837", "8593"]  # '?category=' 쿼리가 붙은 링크에서도 번호만
        assert links == []

    def test_multi_page_tab_exposes_page_links(self):
        url = "https://stellive.me/music/category/279"
        ids, links = sm.parse_tab_page(fixture("stellive_music_category_cover_p1.html"), url)
        assert ids == ["13638", "13636", "13637", "13635", "13634"]
        assert {f"{url}?page={n}" for n in range(2, 11)} <= set(links)

    def test_non_list_page_is_an_error(self):
        with pytest.raises(ListParseError):
            sm.parse_tab_page(b"<html>blocked</html>", "https://stellive.me/music/category/1")


# ============================================================================
# 분류·종류 규칙
# ============================================================================
class TestClassify:
    tabs = {"EP": {"1"}, "SINGLE": {"2", "3"}, "OTHERS": {"4"}, "ALBUM": set()}

    @pytest.mark.parametrize(
        "song_id, leaf, expected",
        [
            ("1", "EP", "EP"),  # 상세가 분류명을 직접 알려 주면 그대로
            ("9", "COVER", "COVER"),
            ("9", "아라하시 타비", "COVER"),  # 멤버 이름(하위 분류) + 어느 탭에도 없음 → COVER
            ("2", "클리셰", "SINGLE"),  # 하위 분류 이름이어도 탭에 있으면 그 분류
            ("4", None, "OTHERS"),
            ("9", None, "COVER"),
        ],
    )
    def test_classify(self, song_id, leaf, expected):
        assert sm.classify(song_id, leaf, self.tabs) == expected


def info(index, artist):
    return tagging.parse_artist(artist, index)


class TestKind:
    @pytest.mark.parametrize(
        "category, artist, kind",
        [
            ("COVER", "Yuzuha Riko", "커버"),
            ("COVER", "STELLIVE", "커버"),  # 분류가 우선
            ("OTHERS", "Akane Lize", "콜라보·OST"),
            ("EP", "STELLIVE", "단체"),
            ("SINGLE", "Cliché", "유닛"),
            ("EP", "Everys", "유닛"),
            ("SINGLE", "Mystic & Universe", "유닛"),
            ("SINGLE", "Neneko Mashiro x Tenko Shibuki", "유닛"),  # 멤버 2명
            ("EP", "Yuzuha Riko", "솔로"),
            ("SINGLE", "Hanako Nana x Todoroki Hajime", "솔로"),  # 현재 멤버 1명 (SPEC: 멤버 1명 → 솔로)
            ("SINGLE", "Airi Kanna", "솔로"),  # 졸업 멤버 단독
            ("SINGLE", "Airi Kanna & VESPERBELL 요미", "유닛"),  # 멤버 0명, 2팀
        ],
    )
    def test_kind(self, index, category, artist, kind):
        assert sm.kind_for(category, info(index, artist)) == kind


def no_pace():
    pass


# ============================================================================
# ① 탭은 끝까지 읽는다
# ============================================================================
class TestReadTabToTheEnd:
    def single_site(self, n=5, **kw):
        return Site([song(i, "SINGLE", leaf="하위분류") for i in range(1, n + 1)], **kw)

    def test_reads_every_page_and_merges_ids_in_order(self):
        site = self.single_site(5, page_size=2)  # 3페이지
        ids = sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert ids == ["1", "2", "3", "4", "5"]
        assert site.calls == [tab_url("SINGLE"), tab_url("SINGLE", 2), tab_url("SINGLE", 3)]  # 각 페이지 한 번씩

    def test_progressive_discovery_when_only_neighbour_pages_are_linked(self):
        # 실제 사이트처럼 현재 페이지 근처 번호만 보여 줘도 끝까지 간다
        site = self.single_site(12, page_size=2, window=1)  # 6페이지, 각 페이지에는 이웃 링크만
        ids = sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert ids == [str(i) for i in range(1, 13)]
        assert len(site.calls) == 6

    def test_page_one_link_with_query_is_not_fetched_twice(self):
        site = self.single_site(4, page_size=2)  # 2페이지 → 2페이지에서 '?page=1' 링크가 나온다
        sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert site.calls.count(tab_url("SINGLE")) == 1 and len(site.calls) == 2

    def test_cycles_terminate(self):
        site = self.single_site(6, page_size=2)  # 모든 페이지가 서로를 가리킨다
        sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert len(site.calls) == len(set(site.calls)) == 3

    def test_single_page_tab_is_one_request(self):
        site = self.single_site(2, page_size=20)
        assert sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace) == ["1", "2"]
        assert len(site.calls) == 1

    def test_empty_tab_is_fine(self):
        site = Site([song(1, "COVER")])
        assert sm.read_tab(tab_url("ALBUM"), get=site, pace=no_pace) == []
        assert len(site.calls) == 1

    def test_only_links_of_the_same_tab_are_followed(self):
        site = Site([song(1, "SINGLE"), song(2, "EP")], page_size=1)
        original = site.tab_html
        site.tab_html = lambda cat, page: original(cat, page).replace(
            '<div class="page_no_wrap">', f'<div class="page_no_wrap"><a href="/music/category/{CIDS["EP"]}?page=1">x</a>'
        )
        sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert site.requests_matching(f"/category/{CIDS['EP']}") == []

    def test_failure_on_a_later_page_is_an_error_not_a_partial_result(self):
        site = self.single_site(6, page_size=2)
        site.fail[tab_url("SINGLE", 2)] = requests.ConnectionError("boom")
        with pytest.raises(TabReadError) as ei:
            sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)
        assert "page=2" in str(ei.value) and "ConnectionError" in str(ei.value)

    def test_http_error_page_is_an_error(self):
        site = self.single_site(4, page_size=2)
        site.fail[tab_url("SINGLE", 2)] = requests.HTTPError("503", response=make_response(503))
        with pytest.raises(TabReadError):
            sm.read_tab(tab_url("SINGLE"), get=site, pace=no_pace)

    def test_non_list_page_is_an_error(self):
        with pytest.raises(TabReadError):
            sm.read_tab(tab_url("SINGLE"), get=lambda url, **kw: make_response(200, b"<html>blocked</html>"), pace=no_pace)

    def test_endless_pagination_hits_the_safety_cap_and_fails(self):
        # 다음 페이지 링크가 끝없이 이어지면 '끝'을 확인할 수 없으니 추측하지 않고 실패한다
        def endless(url, **kw):
            n = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
            html = (
                '<div id="board_list"><div class="gallery_wrap"></div></div>'
                f'<div class="pagination"><div class="page_no_wrap"><a href="/music/category/278?page={n + 1}">n</a></div></div>'
            )
            return make_response(200, html)

        calls = []
        with pytest.raises(TabReadError) as ei:
            sm.read_tab(tab_url("SINGLE"), get=lambda u, **k: (calls.append(u), endless(u))[1], pace=no_pace, max_pages=5)
        assert len(calls) == 5 and "5" in str(ei.value)

    def test_default_cap_is_generous(self):
        assert config.MUSIC_TAB_MAX_PAGES >= 20  # 정상 탭(최대 수 페이지)에는 걸리지 않는다

    def test_pace_is_called_before_every_page_request(self):
        site = self.single_site(6, page_size=2)
        paces = []
        sm.read_tab(tab_url("SINGLE"), get=site, pace=lambda: paces.append(len(site.calls)))
        assert paces == [0, 1, 2]  # 요청 직전마다 한 번 (요청 수 = 호출 수)


# ============================================================================
# ② 경고: COVER 개수 불일치 · 처음 보는 탭
# ============================================================================
def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == LOG and r.levelno == logging.WARNING]


def tabs_of(*pairs):
    return [sm.Tab(name, f"/music/category/{i}", count) for i, (name, count) in enumerate(pairs)]


class TestWarnings:
    # ---- 처음 보는 탭 ----
    def test_known_tabs_only_is_silent(self, caplog):
        tabs = tabs_of(("ALL", None), ("ALBUM", None), ("EP", 7), ("SINGLE", 19), ("COVER", 252), ("OTHERS", 8))
        with caplog.at_level(logging.WARNING, logger=LOG):
            assert sm.check_tabs(tabs) == []
        assert warnings(caplog) == []

    def test_new_tab_warns(self, caplog):
        tabs = tabs_of(("ALL", None), ("ALBUM", None), ("EP", 7), ("SINGLE", 19), ("COVER", 252), ("OTHERS", 8), ("REMIX", 3))
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_tabs(tabs)
        assert len(out) == 1 and "REMIX" in out[0]
        assert any("REMIX" in w and "처음 보는" in w for w in warnings(caplog))

    def test_missing_known_tab_warns(self, caplog):
        tabs = tabs_of(("ALL", None), ("EP", 7), ("SINGLE", 19), ("COVER", 252), ("OTHERS", 8))  # ALBUM이 사라짐
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_tabs(tabs)
        assert len(out) == 1 and "ALBUM" in out[0]

    def test_tab_name_match_ignores_case(self, caplog):
        tabs = tabs_of(("all", None), ("Album", None), ("ep", 7), ("single", 19), ("cover", 252), ("others", 8))
        with caplog.at_level(logging.WARNING, logger=LOG):
            assert sm.check_tabs(tabs) == []

    # ---- 개수 비교 ----
    @staticmethod
    def labels(**kw):
        base = {"ALBUM": None, "EP": 2, "SINGLE": 3, "COVER": 5, "OTHERS": 1}
        base.update(kw)
        return base

    @staticmethod
    def world(extra_cover=0):
        ids = [str(i) for i in range(1, 12 + extra_cover)]  # 1..11 = 11곡 (+ extra)
        tabs = {"ALBUM": set(), "EP": {"1", "2"}, "SINGLE": {"3", "4", "5"}, "OTHERS": {"6"}}
        return ids, tabs  # 나머지 7~11 = COVER 5곡

    def test_consistent_counts_are_silent(self, caplog):
        ids, tabs = self.world()
        with caplog.at_level(logging.WARNING, logger=LOG):
            assert sm.check_counts(ids, tabs, self.labels()) == []
        assert warnings(caplog) == []

    def test_cover_count_mismatch_warns_with_both_numbers(self, caplog):
        ids, tabs = self.world()
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_counts(ids, tabs, self.labels(COVER=6))  # 사이트 라벨은 6, 우리가 계산한 건 5
        assert len(out) == 1
        msg = warnings(caplog)[0]
        assert "COVER" in msg and "5" in msg and "[6]" in msg

    def test_cover_surplus_is_also_detected(self, caplog):
        # 탭에 못 담은 곡이 COVER로 흘러가면 계산한 COVER가 라벨보다 커진다
        ids, tabs = self.world(extra_cover=2)
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_counts(ids, tabs, self.labels())
        assert len(out) == 1 and "COVER" in out[0] and "7" in out[0]

    def test_cover_label_missing_skips_the_cover_check(self, caplog):
        ids, tabs = self.world()
        with caplog.at_level(logging.WARNING, logger=LOG):
            assert sm.check_counts(ids, tabs, self.labels(COVER=None)) == []

    def test_other_tab_label_mismatch_warns_which_also_catches_truncated_reads(self, caplog):
        ids, tabs = self.world()
        tabs["SINGLE"] = {"3", "4"}  # 3페이지 중 일부만 읽었다면
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_counts(ids, tabs, self.labels())
        assert any("SINGLE" in w and "[3]" in w for w in out)

    def test_tab_ids_missing_from_the_full_list_warn(self, caplog):
        ids, tabs = self.world()
        tabs["EP"] = {"1", "999"}
        with caplog.at_level(logging.WARNING, logger=LOG):
            out = sm.check_counts(ids, tabs, self.labels())
        assert any("999" in w and "목록에 없는" in w for w in out)

    # ---- collect 전체 흐름에서의 경고 ----
    def songs(self):
        return [song(1, "COVER"), song(2, "EP", artist="Yuzuha Riko", leaf="EP"), song(3, "SINGLE", leaf="클리셰", artist="Cliché"),
                song(4, "COVER"), song(5, "SINGLE", leaf="하위", artist="STELLIVE")]

    def run(self, site, prev=(), **kw):
        return sm.collect(list(prev), tagging.build_index(MEMBERS()), now=NOW, get=site, sleep=lambda s: None, delay=0, **kw)

    def test_collect_is_silent_when_everything_is_consistent(self, caplog):
        site = Site(self.songs(), page_size=1)
        with caplog.at_level(logging.WARNING, logger=LOG):
            res = self.run(site)
        assert len(res.catalog_items) == 5 and warnings(caplog) == []

    def test_collect_warns_on_cover_label_mismatch_but_still_returns_items(self, caplog):
        site = Site(self.songs(), page_size=1, label_delta={"COVER": 1})
        with caplog.at_level(logging.WARNING, logger=LOG):
            res = self.run(site)
        assert len(res.catalog_items) == 5  # 경고만 하고 계속한다
        assert any("COVER" in w for w in warnings(caplog))

    def test_collect_warns_on_new_tab_but_still_returns_items(self, caplog):
        site = Site(self.songs(), page_size=1, extra_tabs=["REMIX"])
        with caplog.at_level(logging.WARNING, logger=LOG):
            res = self.run(site)
        assert len(res.catalog_items) == 5
        assert any("REMIX" in w for w in warnings(caplog))

    def test_new_tab_is_reported_even_when_there_is_nothing_new(self, caplog):
        site = Site(self.songs(), extra_tabs=["REMIX"])
        first = self.run(Site(self.songs()))
        with caplog.at_level(logging.WARNING, logger=LOG):
            res = self.run(site, prev=first.catalog_items)
        assert res.catalog_items == [] and any("REMIX" in w for w in warnings(caplog))
        assert site.calls == [config.MUSIC_URL]  # 목록 한 번만 — 탭·상세는 요청하지 않는다

    def test_site_total_vs_parsed_items_mismatch_warns(self, caplog):
        site = Site(self.songs(), total=286)  # 목록이 일부만 보이는 경우(페이지네이션 도입 등)
        with caplog.at_level(logging.WARNING, logger=LOG):
            self.run(site)
        assert any("286" in w and "5" in w for w in warnings(caplog))


def MEMBERS():
    import json

    return json.loads((config.DATA_DIR / "members.json").read_text(encoding="utf-8"))


# ============================================================================
# collect: 분류·수집 범위·간격·실패·news 항목
# ============================================================================
class TestCollect:
    def run(self, site, prev=(), now=NOW, **kw):
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("delay", 0)
        return sm.collect(list(prev), tagging.build_index(MEMBERS()), now=now, get=site, **kw)

    def songs(self):
        return [
            song(100, "COVER", artist="Akane Lize", date="2026-09-07"),
            song(101, "EP", artist="Yuzuha Riko", date="2026-07-24", leaf="EP", title="악당주의보"),
            song(102, "SINGLE", artist="Cliché", date="2026-05-19", leaf="클리셰"),
            song(103, "SINGLE", artist="Aokumo Rin", date="2026-04-01", leaf="아오쿠모 린"),
            song(104, "SINGLE", artist="STELLIVE", date="2026-03-01", leaf="스텔라이브"),  # 탭 2페이지에 있다
            song(105, "OTHERS", artist="Hanako Nana x Todoroki Hajime", date="2026-02-01", leaf="OTHERS"),
            song(106, "COVER", artist="STELLIVE", date="2026-01-01"),
            song(107, "ALBUM", artist="Everys", date="2025-12-01", leaf="ALBUM"),
        ]

    def test_catalog_items_shape_and_classification(self):
        res = self.run(Site(self.songs(), page_size=2))
        by_id = {c["id"]: c for c in res.catalog_items}
        assert set(by_id) == {str(n) for n in range(100, 108)}
        assert by_id["101"] == {
            "id": "101", "title": "악당주의보", "artist": "Yuzuha Riko", "who": ["riko"], "category": "EP",
            "kind": "솔로", "date": "2026-07-24", "yt": "V0000000101", "url": "https://stellive.me/music/101",
        }
        got = {i: (c["category"], c["kind"], c["who"]) for i, c in by_id.items()}
        assert got == {
            "100": ("COVER", "커버", ["lize"]),
            "101": ("EP", "솔로", ["riko"]),
            "102": ("SINGLE", "유닛", ["cliche"]),
            "103": ("SINGLE", "솔로", ["rin"]),
            "104": ("SINGLE", "단체", ["all"]),  # 하위 분류 이름('스텔라이브')이지만 SINGLE 탭 2페이지에 있어 분류됨
            "105": ("OTHERS", "콜라보·OST", ["nana"]),
            "106": ("COVER", "커버", ["all"]),
            "107": ("ALBUM", "유닛", ["everys"]),
        }

    def test_result_order_follows_the_list_order(self):
        res = self.run(Site(self.songs()))
        assert [c["id"] for c in res.catalog_items] == [str(n) for n in range(100, 108)]

    def test_already_cataloged_songs_are_not_fetched_again(self):
        site = Site(self.songs())
        first = self.run(site)
        site.calls.clear()
        res = self.run(site, prev=first.catalog_items[:6])  # 6곡은 이미 있다
        assert {c["id"] for c in res.catalog_items} == {"106", "107"}
        assert site.detail_calls() == ["https://stellive.me/music/106", "https://stellive.me/music/107"]

    def test_nothing_unseen_means_only_the_list_is_requested(self):
        site = Site(self.songs())
        full = self.run(site).catalog_items
        site.calls.clear()
        res = self.run(site, prev=full)
        assert res.catalog_items == [] and res.news_items == [] and res.remaining == 0
        assert site.calls == [config.MUSIC_URL]

    def test_detail_limit_per_run_and_remaining(self):
        site = Site([song(n, "COVER") for n in range(1, 11)])
        res = self.run(site, detail_limit=4)
        assert [c["id"] for c in res.catalog_items] == ["1", "2", "3", "4"]  # 목록(최신순) 앞에서부터
        assert res.remaining == 6
        assert len(site.detail_calls()) == 4

    def test_backfill_converges_over_several_runs(self):
        site = Site([song(n, "COVER") for n in range(1, 11)])
        catalog: list = []
        for expected_remaining in (6, 2, 0):
            res = self.run(site, prev=catalog, detail_limit=4)
            catalog += res.catalog_items
            assert res.remaining == expected_remaining
        assert len(catalog) == 10 and len({c["id"] for c in catalog}) == 10

    def test_default_detail_limit_is_forty(self):
        assert config.MUSIC_DETAIL_PER_RUN == 40
        site = Site([song(n, "COVER") for n in range(1, 61)])
        res = sm.collect([], tagging.build_index(MEMBERS()), now=NOW, get=site, sleep=lambda s: None, delay=0)
        assert len(res.catalog_items) == 40 and res.remaining == 20

    def test_non_monotonic_ids_are_handled_by_set_difference(self):
        songs = [song(300), song(298), song(299), song(150)]  # 번호가 날짜·목록 순서와 어긋난다
        res = self.run(Site(songs), prev=[{"id": "299"}, {"id": "300"}])
        assert [c["id"] for c in res.catalog_items] == ["298", "150"]

    def test_request_spacing_every_request_after_the_first_is_paced(self):
        site, sleeps = Site(self.songs(), page_size=2), []
        self.run(site, sleep=sleeps.append, delay=0.5)
        assert len(site.calls) > 10
        assert sleeps == [0.5] * (len(site.calls) - 1)  # 첫 요청(목록) 뒤의 모든 요청 앞에서 정확히 한 번씩

    def test_one_failed_detail_is_skipped_and_retried_next_run(self):
        site = Site([song(1), song(2), song(3)])
        site.fail["https://stellive.me/music/2"] = requests.ConnectionError("boom")
        res = self.run(site)
        assert [c["id"] for c in res.catalog_items] == ["1", "3"] and res.failed == ["2"]
        assert res.remaining == 1
        del site.fail["https://stellive.me/music/2"]
        again = self.run(site, prev=res.catalog_items)
        assert [c["id"] for c in again.catalog_items] == ["2"]

    def test_broken_detail_page_is_skipped(self):
        site = Site([song(1), song(2)])
        original = site.detail_html
        site.detail_html = lambda s: "<html>blocked</html>" if s["id"] == "1" else original(s)
        res = self.run(site)
        assert [c["id"] for c in res.catalog_items] == ["2"] and res.failed == ["1"]

    def test_tab_failure_aborts_without_guessing(self):
        site = Site(self.songs(), page_size=1)
        site.fail[tab_url("SINGLE", 2)] = requests.ConnectionError("boom")
        with pytest.raises(TabReadError):
            self.run(site)
        assert site.requests_matching("/music/category/") and site.detail_calls() == []  # 탭은 읽다 실패했고, 상세는 하나도 안 받았다

    def test_list_parse_error_propagates(self):
        with pytest.raises(ListParseError):
            sm.collect([], tagging.build_index(MEMBERS()), now=NOW, get=lambda u, **k: make_response(200, b"<html>x</html>"), sleep=lambda s: None, delay=0)

    def test_http_error_on_list_propagates(self):
        def get(url, **kw):
            raise requests.HTTPError("503", response=make_response(503))

        with pytest.raises(requests.HTTPError):
            sm.collect([], tagging.build_index(MEMBERS()), now=NOW, get=get, sleep=lambda s: None, delay=0)

    def test_get_receives_only_the_url(self):
        seen = []
        site = Site([song(1)])

        def get(url, **kw):
            seen.append(kw)
            return site(url)

        sm.collect([], tagging.build_index(MEMBERS()), now=NOW, get=get, sleep=lambda s: None, delay=0)
        assert all(kw == {} for kw in seen)  # timeout·UA는 http.get이 강제한다

    # ---- news 항목 ----
    def test_recent_songs_become_news_items_old_ones_do_not(self):
        songs = [
            song(1, "COVER", date="2026-10-05", artist="Akane Lize", title="새 커버"),  # 1일 전
            song(2, "COVER", date="2026-09-22"),  # 14일 전 = 경계(포함)
            song(3, "COVER", date="2026-09-21"),  # 15일 전
            song(4, "COVER", date="2023-06-01"),  # 옛날 곡: 백필로 들어와도 피드에 오르지 않는다
            song(5, "COVER", date="2026-10-20"),  # 예정된 발매
        ]
        res = self.run(Site(songs))
        assert [n["id"] for n in res.news_items] == ["mu-1", "mu-2", "mu-5"]
        assert res.news_items[0] == {
            "id": "mu-1", "date": "2026-10-05", "cat": "음악", "who": ["lize"], "title": "새 커버",
            "url": "https://stellive.me/music/1", "source": "공식 홈페이지", "yt": "V0000000001",
        }
        assert len(res.catalog_items) == 5  # catalog에는 전부

    def test_feed_window_is_configurable_via_config(self):
        assert config.MUSIC_FEED_DAYS == 14

    def test_songs_without_a_current_member_or_group_are_not_fed(self):
        res = self.run(Site([song(1, "COVER", artist="Airi Kanna", date="2026-10-05")]))
        assert len(res.catalog_items) == 1 and res.catalog_items[0]["who"] == []
        assert res.news_items == []

    def test_news_only_for_songs_cataloged_this_run(self):
        site = Site([song(1, "COVER", date="2026-10-05")])
        first = self.run(site)
        again = self.run(site, prev=first.catalog_items)
        assert [n["id"] for n in first.news_items] == ["mu-1"] and again.news_items == []
