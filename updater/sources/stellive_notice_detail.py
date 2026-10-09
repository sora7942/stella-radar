"""공지 상세 stellive.me/news/<번호> → 본문 텍스트 (기능 3, SPEC-v1.1). 일정 추출(Claude)의 입력이다.

3-0에서 확인한 사실 (2026-10-09, 최신 30건, 픽스처 tests/fixtures/stellive_news_detail_*.html):
- 본문은 서버가 렌더링한 HTML의 `div.xe_content`(페이지에 1개)다. `__NEXT_DATA__`·JSON-LD·별도 API는 없다
- **상세 페이지에는 공지 목록 전체가 같이 들어 있다.** `div.bh_title`·`span.ff-nn`·`.bh_category`는 이 공지가 아니라 목록 첫 항목을 잡는다.
  그래서 제목·날짜·분류는 목록(news 항목)의 값을 쓰고, 여기서는 본문 컨테이너 하나만 읽는다
- 포스터 이미지만 있는 공지는 본문이 비어 있거나 한 줄뿐이다 → 글자 수(공백 제외)가 config.EVENTS_NO_TEXT_CHARS보다 적으면 호출하는 쪽이 `no_text`로 처리한다
- 본문 안의 이미지는 읽지 않는다(저장·OCR 없음). 이미지에만 있는 날짜는 놓친다
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import config, http

BODY_SELECTOR = "div.xe_content"
_INVISIBLE = re.compile("[\u200b\u200c\u200d\ufeff]")  # 제로폭 문자


class BodyParseError(ValueError):
    """상세 페이지에서 본문 컨테이너를 찾지 못했다 (레이아웃이 바뀌었거나 차단 페이지)."""


def parse_body(content: bytes) -> str:
    """상세 HTML → 본문 텍스트. 줄 단위로 다듬고 빈 줄은 뺀다. 본문 컨테이너가 없으면 BodyParseError."""
    node = BeautifulSoup(content, "html.parser", from_encoding="utf-8").select_one(BODY_SELECTOR)  # 사이트는 UTF-8. 메타가 없어도 한글이 깨지지 않게 명시
    if node is None:
        raise BodyParseError(f"본문 컨테이너({BODY_SELECTOR})를 찾지 못함 ({len(content)}바이트) — 레이아웃이 바뀌었거나 차단 페이지일 수 있음")
    lines = (" ".join(_INVISIBLE.sub("", line).replace("\xa0", " ").split()) for line in node.get_text("\n", strip=True).splitlines())
    return "\n".join(line for line in lines if line)


def char_count(text: str) -> int:
    """공백을 뺀 글자 수 (no_text 판정 기준)."""
    return len(re.sub(r"\s+", "", text))


def fetch_body(number: str, *, get=http.get) -> str:
    """공지 번호 → 본문 텍스트. HTTP 오류는 requests.HTTPError(.response 포함), 레이아웃 문제는 BodyParseError."""
    return parse_body(get(config.NEWS_ITEM_URL.format(number=number)).content)
