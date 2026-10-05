"""공식 음악 stellive.me/music → catalog 항목(+ 새 곡은 news 항목). SPEC 4·5장.

목록(`/music`)에는 번호·제목·영문 아티스트만 있고 날짜·분류·유튜브 ID가 없다. 그래서
- 처음 보는 번호만 상세(`/music/<번호>`)를 실행당 최대 MUSIC_DETAIL_PER_RUN건, 요청 간 REQUEST_DELAY초 간격으로 받는다
- 분류(ALBUM/EP/SINGLE/COVER/OTHERS)는 상세로는 알 수 없다(커버곡의 상세 분류는 멤버 이름). 분류 탭 페이지에서 판정한다:
  ALBUM·EP·SINGLE·OTHERS 탭(합계 수십 곡)을 **페이지 끝까지** 읽어 거기 있으면 그 분류, 없으면 COVER (COVER 탭은 13페이지라 받지 않는다)
- 탭 읽기에 하나라도 실패하면 분류를 추측하지 않고 이번 실행의 음악 소스를 실패 처리한다 (catalog는 그대로)
- 경고(계속 진행): 계산한 COVER 수 ≠ COVER 탭 라벨의 [숫자], 처음 보는 분류 탭, 탭 라벨 수 불일치, 목록 총건수 불일치
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Comment

from .. import config, http, tagging

log = logging.getLogger(__name__)

CATEGORIES = ("ALBUM", "EP", "SINGLE", "COVER", "OTHERS")  # 공식 사이트의 분류 그대로
KNOWN_TABS = frozenset(CATEGORIES) | {"ALL"}
FETCHED_TABS = ("ALBUM", "EP", "SINGLE", "OTHERS")  # 읽는 탭. COVER는 '그 밖의 전부'로 계산한다

_MUSIC_ID = re.compile(r"^/music/(\d+)")
_DATE = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")
_YT_EMBED = re.compile(r"youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{11})")
_COUNT = re.compile(r"\[(\d+)\]")


class ListParseError(ValueError):
    """목록(또는 분류 탭) 페이지에서 구조를 읽지 못했다 — 차단 페이지이거나 레이아웃이 바뀐 것."""


class DetailParseError(ValueError):
    """상세 페이지에서 제목·날짜를 읽지 못했다."""


class TabReadError(RuntimeError):
    """분류 탭을 끝까지 읽지 못했다. 이 상태로 분류하면 추측이 되므로 실행을 실패시킨다."""


@dataclass(frozen=True)
class ListItem:
    id: str
    title: str
    artist: str | None


@dataclass(frozen=True)
class Tab:
    name: str
    href: str
    count: int | None  # 라벨의 [숫자]. 빈 탭(ALBUM)과 ALL에는 없다


@dataclass
class ListPage:
    items: list[ListItem]
    tabs: list[Tab]
    total: int | None  # '총 N건'


@dataclass(frozen=True)
class Detail:
    title: str
    artist: str | None
    date: str  # YYYY-MM-DD
    yt: str | None
    leaf: str | None  # 상세에 표시된 (하위) 분류. 커버곡은 멤버 이름이다


@dataclass
class MusicResult:
    catalog_items: list = field(default_factory=list)
    news_items: list = field(default_factory=list)
    remaining: int = 0  # 아직 상세를 받지 못한 곡 수 (다음 실행들에서 이어서)
    failed: list = field(default_factory=list)  # 이번에 상세 읽기에 실패한 번호


def _text(node) -> str:
    return " ".join(node.get_text().split())


# ---------------------------------------------------------------- 파서
def parse_list(content: bytes) -> ListPage:
    soup = BeautifulSoup(content, "html.parser")
    items: list[ListItem] = []
    seen: set[str] = set()
    for node in soup.select("div.gallery_wrap div.bh_item"):
        link = node.select_one(".bh_title a[href]") or node.select_one("a[href]")
        m = _MUSIC_ID.match(link["href"]) if link else None
        title_el = node.select_one(".bh_title")
        title = _text(title_el) if title_el else ""
        if not (m and title):
            log.warning("음악 목록 항목을 건너뜀 (필드 누락): %s", _text(node)[:60])
            continue
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        name_el = node.select_one("div.name")
        items.append(ListItem(m.group(1), title, name_el.get_text(strip=True) or None if name_el else None))
    if not items:
        raise ListParseError(f"음악 목록에서 항목을 읽지 못함 ({len(content)}바이트) — 차단 페이지이거나 레이아웃이 바뀌었을 수 있음")

    tabs = []
    for a in soup.select("ul.bh_board_tab a"):
        li = a.find("li")
        if li is None:
            continue
        counts = [m.group(1) for c in li.find_all(string=lambda s: isinstance(s, Comment)) if (m := _COUNT.search(str(c)))]
        tabs.append(Tab(li.get_text(strip=True), a.get("href", ""), int(counts[0]) if counts else None))

    total_el = soup.select_one("div.item_count span")
    total = int(total_el.get_text(strip=True)) if total_el and total_el.get_text(strip=True).isdigit() else None
    return ListPage(items=items, tabs=tabs, total=total)


def parse_detail(content: bytes) -> Detail:
    soup = BeautifulSoup(content, "html.parser")
    header = soup.select_one(".content_header")
    if header is None:
        raise DetailParseError("상세 페이지 구조(.content_header)를 찾지 못함")
    title_el = header.select_one("h1 a") or header.select_one("h1")
    title = _text(title_el) if title_el else ""
    rows = {}
    for tr in soup.select("table.extra tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            rows[th.get_text(strip=True)] = " ".join(td.get_text().replace("\xa0", " ").split())
    d = _DATE.search(rows.get("날짜", ""))
    if not (title and d):
        raise DetailParseError(f"제목 또는 날짜를 읽지 못함 (제목={title!r}, 날짜={rows.get('날짜')!r})")
    iframe = soup.select_one('iframe[src*="youtube"]')
    yt = _YT_EMBED.search(iframe.get("src", "")) if iframe else None
    leaf_el = header.select_one("a.category")
    return Detail(
        title=title,
        artist=rows.get("가수이름") or None,
        date="-".join(d.groups()),
        yt=yt.group(1) if yt else None,
        leaf=leaf_el.get_text(strip=True) if leaf_el else None,
    )


def parse_tab_page(content: bytes, page_url: str) -> tuple[list[str], list[str]]:
    """분류 탭 한 페이지 → (곡 번호들, 페이지네이션 링크들[절대 URL])."""
    soup = BeautifulSoup(content, "html.parser")
    if soup.select_one("#board_list") is None:
        raise ListParseError("음악 목록 페이지가 아님 (#board_list 없음)")
    ids: list[str] = []
    for a in soup.select("div.gallery_wrap div.bh_item a[href]"):
        m = _MUSIC_ID.match(a["href"])  # '/music/12882?category=8591' 처럼 쿼리가 붙어 있다
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    links = [urljoin(page_url, a["href"]) for a in soup.select(".pagination a[href]")]
    return ids, links


# ---------------------------------------------------------------- 분류 탭 읽기
def _normalize_url(url: str) -> str:
    """같은 페이지의 표기 차이를 없앤다: 프래그먼트 제거, '?page=1'은 쿼리 없는 첫 페이지와 같다."""
    u = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(u.query) if not (k == "page" and v == "1")]
    return urlunparse(u._replace(query=urlencode(sorted(query)), fragment=""))


def read_tab(start_url: str, *, get, pace, max_pages: int = config.MUSIC_TAB_MAX_PAGES) -> list[str]:
    """분류 탭을 **끝까지** 읽어 곡 번호를 모은다.

    각 페이지의 페이지네이션 링크(같은 탭만)를 따라가고, 이미 읽은 URL은 건너뛴다(순환·중복 방지).
    중간에 한 페이지라도 실패하면, 또는 max_pages를 넘겨도 끝나지 않으면 TabReadError.
    """
    start = _normalize_url(start_url)
    tab_path = urlparse(start).path
    queue, visited = [start], {start}
    ids: list[str] = []
    fetched = 0
    while queue:
        if fetched >= max_pages:
            raise TabReadError(f"{start_url}: {max_pages}페이지를 읽고도 끝을 확인하지 못함 (안전 상한)")
        url = queue.pop(0)
        pace()
        try:
            page_ids, links = parse_tab_page(get(url).content, url)
        except Exception as e:  # 네트워크·HTTP·구조 오류 모두 '끝까지 못 읽음'
            raise TabReadError(f"{url} 읽기 실패: {type(e).__name__}: {e}") from e
        fetched += 1
        ids += [i for i in page_ids if i not in ids]
        for link in links:
            norm = _normalize_url(link)
            if norm not in visited and urlparse(norm).path == tab_path:
                visited.add(norm)
                queue.append(norm)
    return ids


# ---------------------------------------------------------------- 검증 경고
def check_tabs(tabs: list[Tab]) -> list[str]:
    """목록 페이지의 분류 탭 목록을 점검한다: 처음 보는 탭, 사라진 탭. 경고만 하고 계속한다."""
    names = {t.name.upper() for t in tabs}
    out = []
    for t in tabs:
        if t.name.upper() not in KNOWN_TABS:
            out.append(f"처음 보는 음악 분류 탭: {t.name} ({t.href}) — 이 탭의 곡은 COVER로 분류될 수 있음")
    for name in sorted(KNOWN_TABS - names):
        out.append(f"예상한 음악 분류 탭이 없음: {name}")
    for msg in out:
        log.warning(msg)
    return out


def check_counts(list_ids, tab_ids: dict, labels: dict) -> list[str]:
    """읽은 결과를 탭 라벨의 [숫자]와 맞춰 본다. 다르면 경고(분류가 어긋났거나 탭을 덜 읽었다는 뜻)."""
    all_ids = set(list_ids)
    in_tabs = set().union(*tab_ids.values()) if tab_ids else set()
    out = []
    for name in FETCHED_TABS:
        label = labels.get(name)
        if label is not None and name in tab_ids and len(tab_ids[name]) != label:
            out.append(f"{name} 탭 곡 수 불일치: 읽은 {len(tab_ids[name])}곡 ≠ 탭 라벨 [{label}]")
    stray = sorted(in_tabs - all_ids)
    if stray:
        out.append(f"분류 탭에는 있지만 전체 목록에 없는 곡 {len(stray)}개: {', '.join(stray[:5])}")
    cover = len(all_ids - in_tabs)
    label = labels.get("COVER")
    if label is not None and cover != label:
        out.append(f"COVER 곡 수 불일치: 계산 {cover}곡 ≠ COVER 탭 라벨 [{label}]")
    for msg in out:
        log.warning(msg)
    return out


# ---------------------------------------------------------------- 분류·종류
def classify(song_id: str, leaf: str | None, tab_ids: dict) -> str:
    if leaf and leaf.upper() in CATEGORIES:  # 상세가 분류명을 직접 보여 주면 그대로
        return leaf.upper()
    for name in FETCHED_TABS:
        if song_id in tab_ids.get(name, ()):
            return name
    return "COVER"


def kind_for(category: str, info: tagging.ArtistInfo) -> str:
    """SPEC 4장: COVER→커버, OTHERS→콜라보·OST, 나머지는 아티스트로 — STELLIVE→단체, 유닛명/멤버 2명↑→유닛, 멤버 1명→솔로."""
    if category == "COVER":
        return "커버"
    if category == "OTHERS":
        return "콜라보·OST"
    if info.all:
        return "단체"
    if info.groups or len(info.members) >= 2:
        return "유닛"
    if len(info.members) == 1:
        return "솔로"
    return "솔로" if info.tokens <= 1 else "유닛"  # 현재 멤버가 없는 경우: 졸업 멤버 단독은 솔로, 여럿이면 유닛


# ---------------------------------------------------------------- 수집
def _pacer(sleep, delay):
    """첫 호출은 바로, 이후 호출은 delay초 쉬고 — 모든 요청 앞에서 부른다."""
    first = True

    def pace():
        nonlocal first
        if first:
            first = False
        else:
            sleep(delay)

    return pace


def _feed_item(c: dict) -> dict:
    return {
        "id": f"mu-{c['id']}",
        "date": c["date"],
        "cat": "음악",
        "who": c["who"],
        "title": c["title"],
        "url": c["url"],
        "source": config.OFFICIAL_SOURCE_LABEL,
        "yt": c["yt"],
    }


def collect(
    prev_items: list[dict],
    index: tagging.TagIndex,
    *,
    now,
    get=http.get,
    sleep=time.sleep,
    delay: float = config.REQUEST_DELAY,
    detail_limit: int = config.MUSIC_DETAIL_PER_RUN,
) -> MusicResult:
    """목록 → 미수집 번호의 상세(+분류 탭) → 새 catalog 항목과, 최근 발매곡의 news 항목."""
    pace = _pacer(sleep, delay)
    pace()
    page = parse_list(get(config.MUSIC_URL).content)
    if page.total is not None and page.total != len(page.items):
        log.warning("목록의 '총 %d건'과 읽은 항목 수 %d가 다름 (페이지가 나뉘었거나 레이아웃이 바뀌었을 수 있음)", page.total, len(page.items))
    check_tabs(page.tabs)

    known = {it["id"] for it in prev_items}
    unseen = [it for it in page.items if it.id not in known]
    if not unseen:
        log.info("음악: 새로 볼 곡 없음 (목록 %d곡)", len(page.items))
        return MusicResult()

    # 분류: 미수집 곡이 있을 때만 탭을 읽는다 (평소에는 요청 0회). 하나라도 실패하면 TabReadError로 중단
    by_name = {t.name.upper(): t for t in page.tabs}
    tab_ids: dict[str, set[str]] = {}
    for name in FETCHED_TABS:
        tab = by_name.get(name)
        tab_ids[name] = set(read_tab(urljoin(config.MUSIC_URL, tab.href), get=get, pace=pace)) if tab else set()
    check_counts([it.id for it in page.items], tab_ids, {n: t.count for n, t in by_name.items()})

    result = MusicResult()
    for item in unseen[:detail_limit]:
        pace()
        try:
            detail = parse_detail(get(config.MUSIC_ITEM_URL.format(number=item.id)).content)
        except Exception as e:  # 한 곡의 실패가 나머지를 막지 않는다. 다음 실행에서 다시 시도한다
            log.warning("음악 상세 실패 %s: %s: %s", item.id, type(e).__name__, e)
            result.failed.append(item.id)
            continue
        artist = detail.artist or item.artist or ""
        info = tagging.parse_artist(artist, index)
        category = classify(item.id, detail.leaf, tab_ids)
        result.catalog_items.append(
            {
                "id": item.id,
                "title": detail.title,
                "artist": artist,
                "who": info.who,
                "category": category,
                "kind": kind_for(category, info),
                "date": detail.date,
                "yt": detail.yt,
                "url": config.MUSIC_ITEM_URL.format(number=item.id),
            }
        )
    result.remaining = len(unseen) - len(result.catalog_items)

    # news 피드: 이번에 catalog에 들어온 곡 중 발매일이 최근(MUSIC_FEED_DAYS)인 것만 — 백필로 들어오는 옛날 곡은 올리지 않는다
    today = now.astimezone(config.KST).date()
    for c in result.catalog_items:
        if c["who"] and (today - date_cls.fromisoformat(c["date"])).days <= config.MUSIC_FEED_DAYS:
            result.news_items.append(_feed_item(c))
    log.info("음악: 목록 %d곡 중 미수집 %d곡 → 이번에 %d곡 수집 (남은 %d곡, 실패 %d건)",
             len(page.items), len(unseen), len(result.catalog_items), result.remaining, len(result.failed))
    return result
