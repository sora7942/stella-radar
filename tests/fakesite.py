"""테스트용 가짜 stellive.me/music: 실제 구조의 HTML(목록·상세·분류 탭·페이지네이션)을 만들어 준다.
test_stellive_music.py와 test_main.py가 함께 쓴다."""
import math
import re
from urllib.parse import parse_qs, urlparse

import requests

from conftest import make_response

CIDS = {"ALBUM": 277, "EP": 8591, "SINGLE": 278, "COVER": 279, "OTHERS": 555}
TAB_ORDER = ["ALBUM", "EP", "SINGLE", "COVER", "OTHERS"]


def song(num, category="COVER", *, artist="Akane Lize", date="2026-03-01", leaf=None, title=None):
    return {
        "id": str(num), "category": category, "artist": artist, "date": date,
        "leaf": leaf or ("아라하시 타비" if category == "COVER" else category),
        "title": title or f"곡 {num}", "yt": f"V{num:010d}",
    }


def item_html(s, query=""):
    href = f"/music/{s['id']}{query}"
    return (
        f'<div class="bh bh_item item item1 col-6"><div class="bh bh_item_inner">'
        f'<div class="bh category"><div class="ds-f ai-c"><span>{s["leaf"]}</span></div></div>'
        f'<div class="bh_img_content"><a href="{href}"><img src="/x.jpg"/></a></div>'
        f'<div class="bh_content_wrap"><div class="bh_title ff-nn"><a href="{href}"><span class="bh">\n\t{s["title"]}\t</span></a></div>'
        f'<div class="name ff-nn">{s["artist"]}</div></div></div><a href="{href}"></a></div>'
    )


class Site:
    """가짜 stellive.me/music. calls에 요청 URL을 기록하고, fail[url]에 예외를 넣으면 그 URL이 실패한다."""

    def __init__(self, songs, *, page_size=2, window=None, label_delta=None, extra_tabs=(), drop_tabs=(), total=None):
        self.songs, self.page_size, self.window = songs, page_size, window
        self.label_delta, self.extra_tabs, self.drop_tabs, self.total = label_delta or {}, extra_tabs, drop_tabs, total
        self.calls: list[str] = []
        self.fail: dict[str, Exception] = {}

    def of(self, category):
        return [s for s in self.songs if s["category"] == category]

    def list_html(self):
        tabs = ['<a class="on" href="/music"><li>ALL</li></a>']
        for cat in TAB_ORDER:
            if cat in self.drop_tabs:
                continue
            n = len(self.of(cat)) + self.label_delta.get(cat, 0)
            label = f"<!--<em>[{n}]</em>-->" if n else "<!---->"
            tabs.append(f'<a href="/music/category/{CIDS[cat]}"><li>{cat}{label}</li></a>')
        for name in self.extra_tabs:
            tabs.append(f'<a href="/music/category/999"><li>{name}<!----></li></a>')
        total = self.total if self.total is not None else len(self.songs)
        return (
            f'<ul class="bh_board_tab style2">{"".join(tabs)}</ul><div class="item_count">총 <span>{total}</span>건</div>'
            f'<div class="bh board_list" id="board_list"><div class="gallery_wrap">{"".join(item_html(s) for s in self.songs)}</div></div>'
        )

    def pages(self, cat):
        return max(1, math.ceil(len(self.of(cat)) / self.page_size))

    def tab_html(self, cat, page):
        chunk = self.of(cat)[(page - 1) * self.page_size : page * self.page_size]
        links = [
            f'<a href="/music/category/{CIDS[cat]}?page={p}" class="direction">{p}</a>'
            for p in range(1, self.pages(cat) + 1)
            if p != page and (self.window is None or abs(p - page) <= self.window)
        ]
        return (
            f'<div class="bh board_list" id="board_list"><div class="gallery_wrap">{"".join(item_html(s, f"?category={CIDS[cat]}") for s in chunk)}</div></div>'
            f'<div class="pagination"><div class="prev_wrap"><a class="direction prev" title="Prev"><i></i></a></div>'
            f'<div class="page_no_wrap"><strong class="direction active">{page}</strong>{"".join(links)}</div>'
            f'<div class="next_wrap"><a class="direction next" title="Next"><i></i></a></div></div>'
        )

    def detail_html(self, s):
        return (
            f'<div class="bh board"><div class="content_header_wrap"><div class="content_header"><span class="ff-nn">'
            f'<a href="/music/category/417" class="category">{s["leaf"]}</a></span>'
            f'<h1 class="ff-nn"><a href="https://stellive.me/music/{s["id"]}">{s["title"]}</a></h1></div>'
            f'<div class="extra_wrap"><table class="extra"><tbody><tr><th scope="row">가수이름</th><td colspan="3">{s["artist"]}&nbsp;</td></tr>'
            f'<tr><th scope="row">날짜</th><td colspan="3">{s["date"].replace("-", ".")}</td></tr></tbody></table></div></div>'
            f'<div class="content_body"><div class="youtube_converted"><iframe src="https://www.youtube.com/embed/{s["yt"]}"></iframe></div></div></div>'
        )

    def __call__(self, url, **kw):
        self.calls.append(url)
        if url in self.fail:
            raise self.fail[url]
        u = urlparse(url)
        parts = u.path.strip("/").split("/")
        if u.path == "/music":
            html = self.list_html()
        elif parts[:2] == ["music", "category"]:
            cat = next(c for c, cid in CIDS.items() if str(cid) == parts[2])
            page = int(parse_qs(u.query).get("page", ["1"])[0])
            html = self.tab_html(cat, page)
        else:
            s = next((s for s in self.songs if s["id"] == parts[1]), None)
            if s is None:
                raise requests.HTTPError("404", response=make_response(404))
            html = self.detail_html(s)
        return make_response(200, html.encode("utf-8"))

    def requests_matching(self, needle):
        return [c for c in self.calls if needle in c]

    def detail_calls(self):
        """상세 페이지(/music/<번호>) 요청만. 분류 탭(/music/category/<번호>)은 제외."""
        return [c for c in self.calls if re.fullmatch(r"/music/\d+", urlparse(c).path)]


def tab_url(cat, page=None):
    base = f"https://stellive.me/music/category/{CIDS[cat]}"
    return base if not page or page == 1 else f"{base}?page={page}"


