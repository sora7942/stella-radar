import pytest
import requests

from conftest import make_response
from updater import config, tagging
from updater.sources import stellive_news
from updater.sources.stellive_news import ListParseError


@pytest.fixture(scope="module")
def index(members):
    return tagging.build_index(members)


@pytest.fixture(scope="module")
def items(index):
    html = (config.ROOT / "tests" / "fixtures" / "stellive_news_list.html").read_bytes()
    return stellive_news.parse_list(html, index, limit=100)


def by_id(items):
    return {it["id"]: it for it in items}


def test_fixture_yields_all_16_items_in_page_order(items):
    assert len(items) == 16
    assert [it["id"] for it in items][:3] == ["sl-14044", "sl-14028", "sl-14004"]


def test_first_item_fields(items):
    assert items[0] == {
        "id": "sl-14044",
        "date": "2026-10-05",  # 날짜만 (시각 없음)
        "cat": "공지",  # OTHERS
        "who": ["all"],
        "title": "<2026 STELLIVE POP-UP STELLA MODE:ON> 예약 링크 안내 공지",  # &lt; &gt; 복원
        "url": "https://stellive.me/news/14044",
        "source": "공식 홈페이지",
    }
    assert "added" not in items[0]  # added는 병합 단계에서


def test_category_mapping(items):
    cats = by_id(items)
    assert cats["sl-14028"]["cat"] == "굿즈"  # GOODS
    assert cats["sl-13907"]["cat"] == "이벤트"  # EVENT
    assert cats["sl-14044"]["cat"] == "공지"  # OTHERS
    # MUSIC(8493·8478·8455)·CONTENTS(11721)도 SPEC대로 '그 외 → 공지'
    others = {it["cat"] for it in items if it["id"] in {"sl-8493", "sl-8478", "sl-8455", "sl-11721"}}
    assert others == {"공지"}
    assert sum(1 for it in items if it["id"] in {"sl-8493", "sl-8478", "sl-8455", "sl-11721"}) == 4


def test_members_are_tagged_from_title(items):
    cats = by_id(items)
    assert cats["sl-14004"]["who"] == ["lize"]  # 2026 아카네 리제 생일 한정 굿즈
    assert cats["sl-8478"]["who"] == ["yuni"]  # 아야츠노 유니 1st EP
    assert cats["sl-11721"]["who"] == ["lize"]  # 『AKANE LIZE : OVT. FIRST SOLO CONCERT』 (영문)
    assert cats["sl-14028"]["who"] == ["all"]  # <STELLIVE 여름 신의상 …>
    assert cats["sl-13930"]["who"] == ["all"]  # <2026 STELLIVE POP-UP STELLA MODE:ON>


def test_zero_width_space_is_removed_from_titles(items):
    assert all("​" not in it["title"] and "\xa0" not in it["title"] for it in items)
    t = by_id(items)["sl-13887"]["title"]
    assert t.endswith("실루엣 공개!")  # 원문 끝에 제로폭 공백이 붙어 있다


def test_limit_takes_the_newest_n_in_page_order(index):
    html = (config.ROOT / "tests" / "fixtures" / "stellive_news_list.html").read_bytes()
    got = stellive_news.parse_list(html, index, limit=5)
    assert [it["id"] for it in got] == ["sl-14044", "sl-14028", "sl-14004", "sl-13962", "sl-13930"]


def test_default_limit_comes_from_config(index):
    assert config.NEWS_LIST_LIMIT == 30


@pytest.mark.parametrize("content", [b"", b"<html><body>blocked</body></html>", b'<div class="webzine_wrap"></div>'])
def test_no_items_is_a_parse_error_not_an_empty_success(content, index):
    # 레이아웃이 바뀌거나 차단 페이지가 오면 조용히 빈 결과가 되는 대신 소스 실패로 드러나야 한다
    with pytest.raises(ListParseError):
        stellive_news.parse_list(content, index, limit=30)


def test_broken_items_are_skipped_but_not_all(index):
    html = """
    <div class="webzine_wrap">
      <div class="bh_item"><div class="bh_category"><span>GOODS</span></div></div>
      <div class="bh_item">
        <div class="bh_category"><span>EVENT</span></div>
        <a class="title" href="/news/1"><span>제목</span></a>
        <span class="ff-nn">2026.10.01</span>
      </div>
    </div>""".encode("utf-8")
    got = stellive_news.parse_list(html, index, limit=30)
    assert [it["id"] for it in got] == ["sl-1"] and got[0]["cat"] == "이벤트"


def test_unparsable_date_item_is_skipped(index):
    html = """<div class="webzine_wrap">
      <div class="bh_item"><div class="bh_category"><span>GOODS</span></div>
        <a class="title" href="/news/2"><span>t</span></a><span class="ff-nn">어제</span></div>
      <div class="bh_item"><div class="bh_category"><span>GOODS</span></div>
        <a class="title" href="/news/3"><span>t3</span></a><span class="ff-nn">2026.10.02</span></div></div>""".encode("utf-8")
    assert [it["id"] for it in stellive_news.parse_list(html, index, limit=30)] == ["sl-3"]


def test_duplicate_numbers_are_dropped(index):
    one = """<div class="bh_item"><div class="bh_category"><span>GOODS</span></div>
      <a class="title" href="/news/5"><span>t</span></a><span class="ff-nn">2026.10.02</span></div>"""
    html = f'<div class="webzine_wrap">{one}{one}</div>'.encode("utf-8")
    assert len(stellive_news.parse_list(html, index, limit=30)) == 1


def test_collect_uses_given_get_with_the_news_url(index):
    html = (config.ROOT / "tests" / "fixtures" / "stellive_news_list.html").read_bytes()
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        return make_response(200, html)

    got = stellive_news.collect(index, get=get)
    assert calls == [(config.NEWS_URL, {})]  # timeout·UA는 http.get이 강제 — 소스가 인자를 덧붙이지 않는다
    assert len(got) == 16  # 픽스처엔 16건뿐이라 limit(30) 미만


def test_collect_propagates_http_errors(index):
    def get(url, **kw):
        raise requests.HTTPError("503", response=make_response(503))

    with pytest.raises(requests.HTTPError):
        stellive_news.collect(index, get=get)
