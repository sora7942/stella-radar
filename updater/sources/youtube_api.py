"""YouTube Data API v3 → news 항목 (SPEC 5장 '유튜브 새 영상'의 기본 수집 경로). RSS(youtube_rss.py)는 API 키가 없거나
할당량이 초과됐을 때만 쓰는 대체 경로다. 반환하는 항목 형식은 RSS와 같다.

- 채널 → 업로드 재생목록 ID는 channels.list(part=contentDetails)로 구해 status.json에 캐시한다(멤버 key별 `uploads`,
  공식 채널은 "official"). 캐시된 ID가 더는 유효하지 않으면(playlistNotFound) 그 채널만 다시 구한다.
- 채널마다 playlistItems.list(maxResults=15, part=snippet,contentDetails)로 최신 영상을 가져온다. 비용은 호출당 1유닛.
- 게시 시각은 contentDetails.videoPublishedAt(영상 자체의 게시 시각). snippet.publishedAt은 '재생목록에 추가된 시각'이라 쓰지 않는다.
  삭제·비공개 영상은 videoPublishedAt이 없으므로 건너뛴다. 쇼츠·라이브 다시보기·프리미어 커버는 응답에서 일반 영상과 구별되지 않으며 그대로 포함한다.
- **API 키는 URL이 아니라 X-Goog-Api-Key 헤더로만 보낸다.** 오류는 HTTP 상태와 Google의 reason 코드만 기록하고, 예외 메시지·응답 본문은
  쓰지 않는다(`raise … from None`으로 원래 예외도 숨긴다). 키가 로그·예외 메시지에 섞이지 않게 하는 것이 이 모듈의 불변 조건이다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode

import requests

from .. import config, http, tagging, timeutil
from .youtube_rss import WATCH_URL, Channel

log = logging.getLogger(__name__)

_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}  # 이때만 RSS로 대체한다 (rateLimitExceeded 등 일시적 제한은 다음 실행에 다시 시도)
_CHANNELS_PER_CALL = 50  # channels.list의 id 상한


class ApiError(RuntimeError):
    """API 호출 실패. 메시지에는 HTTP 상태·reason 코드만 담긴다 (키·URL·응답 본문 없음)."""


class QuotaExceeded(ApiError):
    """일일 할당량 초과 → 남은 채널은 RSS로 수집한다."""


class PlaylistNotFound(ApiError):
    """캐시된 업로드 재생목록 ID가 더는 유효하지 않다."""


@dataclass
class Result:
    items: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    uploads: dict = field(default_factory=dict)  # 이번에 새로 구한(바뀐) 캐시: {멤버 key 또는 "official": 업로드 재생목록 ID}
    remaining: list = field(default_factory=list)  # 할당량 초과로 처리하지 못한 채널 → RSS 대상
    quota_exceeded: bool = False


def cache_key(channel: Channel) -> str:
    return channel.owner or "official"


def _reason(response) -> str | None:
    try:
        return response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def _call(get, endpoint: str, params: dict, api_key: str) -> dict:
    url = f"{config.YOUTUBE_API_URL}/{endpoint}?{urlencode(params)}"  # 키는 URL에 넣지 않는다
    try:
        return get(url, headers={config.YOUTUBE_API_KEY_HEADER: api_key}).json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        reason = _reason(e.response)
        detail = f"HTTP {status} {reason or '-'}"
        if status == 403 and reason in _QUOTA_REASONS:
            raise QuotaExceeded(detail) from None
        if status == 404 and reason == "playlistNotFound":
            raise PlaylistNotFound(detail) from None
        raise ApiError(detail) from None
    except (requests.RequestException, ValueError) as e:  # 연결·타임아웃·JSON 오류. 종류만 남긴다 (메시지에 URL이 있을 수 있다)
        raise ApiError(type(e).__name__) from None


def resolve_uploads(channel_ids: list[str], api_key: str, get=http.get) -> dict[str, str]:
    """channels.list로 {채널 ID: 업로드 재생목록 ID}. 응답에 없는 채널(삭제·종료)은 결과에서 빠진다."""
    out: dict[str, str] = {}
    for i in range(0, len(channel_ids), _CHANNELS_PER_CALL):
        data = _call(get, "channels", {"part": "contentDetails", "id": ",".join(channel_ids[i : i + _CHANNELS_PER_CALL])}, api_key)
        for item in data.get("items") or []:
            uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if item.get("id") and uploads:
                out[item["id"]] = uploads
    return out


def fetch_playlist(playlist_id: str, api_key: str, get=http.get) -> dict:
    params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": config.YOUTUBE_API_MAX_RESULTS}
    return _call(get, "playlistItems", params, api_key)


def parse_playlist(data: dict, channel: Channel, index: tagging.TagIndex) -> list[dict]:
    """playlistItems.list 응답 → news 항목(added는 병합 단계에서 붙는다). youtube_rss.parse_feed와 같은 형식."""
    items = []
    skipped = 0
    for entry in data.get("items") or []:
        snippet, details = entry.get("snippet") or {}, entry.get("contentDetails") or {}
        video_id = details.get("videoId") or (snippet.get("resourceId") or {}).get("videoId")
        published = details.get("videoPublishedAt")  # 영상 자체의 게시 시각. snippet.publishedAt(재생목록 추가 시각)은 쓰지 않는다
        title = (snippet.get("title") or "").strip()
        if not (video_id and published and title):  # 삭제·비공개 영상에는 videoPublishedAt이 없다
            skipped += 1
            continue
        try:
            date = timeutil.to_kst_iso(published)  # RFC 3339 UTC('…Z') → +09:00
        except ValueError:
            log.warning("%s: 게시 시각을 읽을 수 없는 항목을 건너뜀", channel.source)
            continue
        items.append({
            "id": f"yt-{video_id}",
            "date": date,
            "cat": "영상",
            "who": [channel.owner] if channel.owner else tagging.tag_text(title, index),
            "title": title,
            "url": WATCH_URL.format(video_id=video_id),
            "source": channel.source,
            "yt": video_id,
        })
    if skipped:
        log.info("%s: 삭제·비공개 등으로 %d개 항목을 건너뜀", channel.source, skipped)
    return items


def collect(channels: list[Channel], index: tagging.TagIndex, *, api_key: str, cached: dict[str, str] | None = None, get=http.get) -> Result:
    """모든 채널 수집. 채널 하나의 실패는 다른 채널을 막지 않는다. 할당량이 초과되면 거기서 멈추고 못 한 채널을 remaining에 담는다.
    같은 영상은 먼저 나온 채널(개인 채널 우선)이 이긴다."""
    res = Result()
    cached = cached or {}
    playlist_of = {c.yt_id: cached[cache_key(c)] for c in channels if cached.get(cache_key(c))}

    need = [c for c in channels if c.yt_id not in playlist_of]
    if need:
        try:
            resolved = resolve_uploads([c.yt_id for c in need], api_key, get)
        except QuotaExceeded:
            res.quota_exceeded, res.remaining = True, list(channels)
            return res
        except ApiError as e:
            log.warning("유튜브 API 채널 정보(channels.list) 실패 — %s", e)
            resolved = {}
            res.errors.append(f"채널 정보(channels.list): {e}")
        for c in need:
            if c.yt_id in resolved:
                playlist_of[c.yt_id] = resolved[c.yt_id]
                res.uploads[cache_key(c)] = resolved[c.yt_id]

    seen: set[str] = set()
    for n, channel in enumerate(channels):
        playlist_id = playlist_of.get(channel.yt_id)
        if not playlist_id:  # channels.list가 실패했거나 응답에 없는 채널
            msg = f"{channel.source}: 업로드 재생목록을 찾지 못함"
            log.warning("유튜브 API 채널 실패 — %s", msg)
            res.errors.append(msg)
            continue
        try:
            try:
                data = fetch_playlist(playlist_id, api_key, get)
            except PlaylistNotFound:  # 캐시가 낡았다 → 이 채널만 다시 구해서 한 번 더
                fresh = resolve_uploads([channel.yt_id], api_key, get).get(channel.yt_id)
                if not fresh or fresh == playlist_id:
                    raise
                res.uploads[cache_key(channel)] = fresh
                data = fetch_playlist(fresh, api_key, get)
            parsed = parse_playlist(data, channel, index)
        except QuotaExceeded:
            res.quota_exceeded, res.remaining = True, list(channels[n:])
            break
        except ApiError as e:
            msg = f"{channel.source}: {e}"
            log.warning("유튜브 API 채널 실패 — %s", msg)
            res.errors.append(msg)
            continue
        except Exception as e:  # 예상 밖의 형식 등. 메시지는 쓰지 않고 종류만 남긴다
            msg = f"{channel.source}: {type(e).__name__}"
            log.warning("유튜브 API 채널 실패 — %s", msg)
            res.errors.append(msg)
            continue
        for item in parsed:
            if item["id"] not in seen:
                seen.add(item["id"])
                res.items.append(item)
    return res
