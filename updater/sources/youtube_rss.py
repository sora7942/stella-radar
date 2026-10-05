"""유튜브 RSS → news 항목. 멤버 11명 + 공식 채널 = 12개 채널, 채널당 최신 15개 (SPEC 5장).

- 개인 채널 영상은 채널 주인만 태그, 공식 채널 영상은 제목에서 멤버·유닛 이름을 찾아 태그(없으면 all)
- RSS의 published는 UTC → +09:00으로 변환해 저장
- 한 채널이 실패해도 나머지는 계속한다
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import feedparser

from .. import config, http, tagging, timeutil

log = logging.getLogger(__name__)

OFFICIAL_SOURCE = "스텔라이브 공식 유튜브"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


class FeedParseError(ValueError):
    """RSS가 아닌 응답(차단 페이지·빈 응답 등)."""


@dataclass(frozen=True)
class Channel:
    yt_id: str
    source: str  # news 항목의 source 문구
    owner: str | None  # 멤버 key. None이면 공식 채널(제목 태깅)


def channels_from_members(members: dict) -> list[Channel]:
    """members.json → 채널 목록 (멤버 순서대로, 마지막이 공식). yt_id가 없는 멤버는 건너뛴다."""
    channels = [
        Channel(m["yt_id"], f"{m['n']} 유튜브", key) for key, m in members["members"].items() if m.get("yt_id")
    ]
    official = members.get("official", {}).get("yt_id")
    if official:
        channels.append(Channel(official, OFFICIAL_SOURCE, None))
    return channels


def _video_id(entry) -> str | None:
    vid = entry.get("yt_videoid")
    if vid:
        return vid
    entry_id = entry.get("id") or ""
    return entry_id.removeprefix("yt:video:") if entry_id.startswith("yt:video:") else None


def parse_feed(content: bytes, channel: Channel, index: tagging.TagIndex) -> list[dict]:
    """RSS 바이트 → news 항목 목록(added는 병합 단계에서 붙는다)."""
    parsed = feedparser.parse(content)
    # feedparser는 HTML·빈 응답에도 예외 없이 bozo=False, 빈 결과를 돌려준다 → 피드 제목으로 RSS인지 판정
    if not parsed.feed.get("title"):
        raise FeedParseError(f"RSS가 아닌 응답 ({len(content)}바이트)")

    items = []
    for entry in parsed.entries:
        video_id = _video_id(entry)
        published = entry.get("published")
        title = (entry.get("title") or "").strip()
        if not (video_id and published and title):
            log.warning("%s: 필드가 빠진 항목을 건너뜀 (id=%s)", channel.source, entry.get("id"))
            continue
        items.append(
            {
                "id": f"yt-{video_id}",
                "date": timeutil.to_kst_iso(published),
                "cat": "영상",
                "who": [channel.owner] if channel.owner else tagging.tag_text(title, index),
                "title": title,
                "url": WATCH_URL.format(video_id=video_id),
                "source": channel.source,
                "yt": video_id,
            }
        )
    if not items:
        log.warning("%s: 영상이 하나도 없음", channel.source)
    return items


def collect(
    channels: list[Channel],
    index: tagging.TagIndex,
    *,
    get=http.get,
    delay: float = config.REQUEST_DELAY,
    sleep=time.sleep,
) -> tuple[list[dict], list[str]]:
    """모든 채널 수집 → (항목, 실패 메시지). 같은 영상은 먼저 나온 채널(개인 채널 우선)이 이긴다."""
    items: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for i, channel in enumerate(channels):
        if i:
            sleep(delay)
        try:
            for item in parse_feed(get(config.YOUTUBE_FEED_URL.format(channel_id=channel.yt_id)).content, channel, index):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
        except Exception as e:  # 채널 하나의 실패(네트워크·형식)가 다른 채널을 막지 않게 한다
            msg = f"{channel.source}: {type(e).__name__}: {e}"
            log.warning("유튜브 채널 실패 — %s", msg)
            errors.append(msg)
    return items, errors
