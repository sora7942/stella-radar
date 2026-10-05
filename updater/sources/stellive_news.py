"""공식 공지 stellive.me/news → news 항목 (SPEC 5장).

- 목록 한 페이지에 전체(360건)가 들어 있다. 페이지 순서(최신순)대로 앞에서 NEWS_LIST_LIMIT건만 쓴다
- 날짜는 YYYY.MM.DD(시각 없음) → 'YYYY-MM-DD'
- 분류: GOODS→굿즈, EVENT→이벤트, 그 외(OTHERS·MUSIC·CONTENTS)→공지
- 항목이 하나도 안 나오면(차단 페이지·레이아웃 변경) 빈 성공이 아니라 오류
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .. import config, http, tagging

log = logging.getLogger(__name__)

CATEGORY_MAP = {"GOODS": "굿즈", "EVENT": "이벤트"}  # 그 외는 '공지'
_NUMBER = re.compile(r"/news/(\d+)")
_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
_INVISIBLE = re.compile("[​‌‍﻿]")  # 제목 끝에 섞이는 제로폭 문자


class ListParseError(ValueError):
    """공지 목록에서 항목을 하나도 못 읽었다."""


def _clean_title(text: str) -> str:
    return " ".join(_INVISIBLE.sub("", text).replace("\xa0", " ").split())


def parse_list(content: bytes, index: tagging.TagIndex, limit: int = config.NEWS_LIST_LIMIT) -> list[dict]:
    """목록 HTML → 앞에서 limit건의 news 항목 (added는 병합 단계에서 붙는다)."""
    soup = BeautifulSoup(content, "html.parser")
    items: list[dict] = []
    seen: set[str] = set()
    for node in soup.select("div.webzine_wrap div.bh_item"):
        title_link = node.select_one("a.title")
        cat_el = node.select_one(".bh_category span")
        date_el = node.select_one("span.ff-nn")
        number = _NUMBER.search(title_link.get("href", "")) if title_link else None
        date = _DATE.search(date_el.get_text()) if date_el else None
        title = _clean_title(title_link.get_text()) if title_link else ""
        if not (number and date and title and cat_el):
            log.warning("공지 항목을 건너뜀 (필드 누락): %s", " ".join(node.get_text().split())[:60])
            continue
        news_id = f"sl-{number.group(1)}"
        if news_id in seen:
            continue
        seen.add(news_id)
        items.append(
            {
                "id": news_id,
                "date": "-".join(date.groups()),
                "cat": CATEGORY_MAP.get(cat_el.get_text(strip=True).upper(), "공지"),
                "who": tagging.tag_text(title, index),
                "title": title,
                "url": config.NEWS_ITEM_URL.format(number=number.group(1)),
                "source": config.OFFICIAL_SOURCE_LABEL,
            }
        )
        if len(items) >= limit:
            break
    if not items:
        raise ListParseError(f"공지 목록에서 항목을 읽지 못함 ({len(content)}바이트) — 차단 페이지이거나 레이아웃이 바뀌었을 수 있음")
    return items


def collect(index: tagging.TagIndex, *, get=http.get, limit: int = config.NEWS_LIST_LIMIT) -> list[dict]:
    return parse_list(get(config.NEWS_URL).content, index, limit)
