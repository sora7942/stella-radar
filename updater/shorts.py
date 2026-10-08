"""쇼츠 판별 (SPEC 4·5장, news.json `short`). 유튜브가 직접 분류한 채널의 쇼츠 탭(UUSH…)·동영상 탭(UULF…) 재생목록에 영상이 들어 있는지로 정한다.

규칙 (SPEC 5장, 2026-10-09 사용자 결정):
- 대상: id가 `yt-`로 시작하는 news 항목 중 `short` 필드가 **없는** 것. (`mu-` 음악 항목은 채널을 알 수 없어 제외한다)
- 그 영상의 채널만 조회한다: 채널마다 UUSH 첫 페이지(maxResults=50) 1회, 그 뒤에도 정해지지 않은 항목이 있으면 UULF 첫 페이지 1회. 실행당 같은 목록을 두 번 부르지 않는다.
- UUSH에 있으면 `short: true`, UULF에 있으면 `short: false`. 둘 다 없으면 필드를 만들지 않고 다음 실행에 다시 시도한다.
- 처음 발견(`added`) 뒤 24시간이 지나도 둘 다 없으면 `short: false`로 확정한다 (라이브 다시보기·예약 영상 등). 백필 때 기존 영상도 같은 규칙이다.
- **한 번 정해진 값은 바꾸지 않는다** — 대상은 필드가 없는 항목뿐이다.
- 조회가 실패하면(오류·할당량 초과·키 거부) 그 조회에 기대는 항목은 아무것도 바꾸지 않고 다음 실행에 다시 시도한다. 채널 단위로 전부-아니면-전무다:
  그 채널의 필요한 목록을 모두 읽은 뒤에만 값을 정한다. 할당량 초과·키 거부는 남은 채널 조회도 멈춘다. 이 모듈은 API 키가 있을 때만 호출된다 (RSS 대체 경로에서는 main.py가 건너뛴다).
- 한 채널의 UUSH/UULF 목록이 404(playlistNotFound)면 '그 탭에 영상이 없다'로 본다 (쇼츠를 올린 적 없는 채널 등).

알려진 한계: 판별은 첫 페이지(최신 50개)만 본다. 업데이터가 24시간 넘게 멈췄다가 돌아오면 첫 페이지 밖으로 밀려난 오래된 쇼츠는 24시간 규칙에 따라 일반(false)으로 확정될 수 있다.
호출은 playlistItems.list(호출당 1유닛)뿐이다 — `config.YOUTUBE_API_ENDPOINTS` 허용 목록 그대로이고 search.list는 쓰지 않는다.
오류는 HTTP 상태·reason·예외 종류만 기록한다(youtube_api와 같은 불변 조건: 키·URL·응답 본문 금지).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config, http, timeutil
from .sources import youtube_api
from .sources.youtube_rss import Channel

log = logging.getLogger(__name__)


@dataclass
class Report:
    pending: int = 0  # 이번 실행 시작 때 short 필드가 없던 yt- 항목 수
    short: int = 0  # 이번에 short:true로 정함
    long: int = 0  # 이번에 short:false로 정함 (UULF에서 확인)
    confirmed_long: int = 0  # 이번에 24시간 규칙으로 short:false로 확정
    undecided: int = 0  # 이번에도 정해지지 않아 필드 없이 남음 (다음 실행에 재시도)
    channels: int = 0  # 조회를 시도한 채널 수
    calls: int = 0  # playlistItems.list 호출 수 (= 유닛 수, 실패한 호출 포함)
    failed_channels: int = 0  # 조회 실패로 건너뛴 채널 수
    unmatched: int = 0  # 채널을 알 수 없어 건너뛴 항목 수
    aborted: str | None = None  # 할당량 초과·키 거부로 중단했다면 "HTTP 403 quotaExceeded" 같은 상태·reason

    def summary(self) -> str:
        text = (f"쇼츠 판별: 대상 {self.pending}개 → 쇼츠 {self.short} · 일반 {self.long + self.confirmed_long}"
                f"(24시간 확정 {self.confirmed_long}) · 미정 {self.undecided} · 조회 채널 {self.channels}개, API {self.calls}회")
        if self.failed_channels:
            text += f", 조회 실패 채널 {self.failed_channels}개"
        if self.unmatched:
            text += f", 채널 불명 {self.unmatched}개"
        if self.aborted:
            text += f", 중단({self.aborted})"
        return text


def is_pending(item: dict) -> bool:
    """판별 대상: yt-로 시작하는 id, videoId(yt) 있음, short 필드 없음. 한 번 정해진 값(true·false 어느 쪽이든)은 대상이 아니다."""
    return str(item.get("id", "")).startswith("yt-") and bool(item.get("yt")) and "short" not in item


def video_ids(data: dict) -> set[str]:
    """playlistItems.list 응답 → videoId 집합."""
    out = set()
    for entry in data.get("items") or []:
        vid = (entry.get("contentDetails") or {}).get("videoId") or ((entry.get("snippet") or {}).get("resourceId") or {}).get("videoId")
        if vid:
            out.add(vid)
    return out


def _aged(item: dict, now: datetime) -> bool:
    """처음 발견(added)한 지 24시간이 지났는가. 시각을 읽을 수 없으면 확정하지 않는다."""
    try:
        return now - timeutil.parse_kst(item["added"]) >= timedelta(hours=config.SHORTS_CONFIRM_HOURS)
    except (KeyError, ValueError, TypeError):
        log.warning("쇼츠 판별: added를 읽을 수 없어 24시간 확정을 건너뜀: %s", item.get("id"))
        return False


def fill(items: list[dict], channels: list[Channel], *, api_key: str, now: datetime, get=http.get) -> Report:
    """items(news 항목, 제자리에서 수정)의 판별 대상에 short를 채운다. 결과 요약을 돌려준다.
    예상 밖의 오류(코드 결함)는 그대로 올라간다 — 호출하는 쪽(main.py)이 경고만 남기고 계속한다."""
    rep = Report()
    pending = [it for it in items if is_pending(it)]
    rep.pending = len(pending)
    if not pending:
        return rep
    by_source = {c.source: c for c in channels}
    groups: dict[str, tuple[Channel, list[dict]]] = {}
    for it in pending:
        ch = by_source.get(it.get("source"))
        if ch is None or not str(ch.yt_id).startswith("UC"):
            rep.unmatched += 1
            continue
        groups.setdefault(ch.yt_id, (ch, []))[1].append(it)

    def fetch(prefix: str, channel_id: str) -> set[str]:
        rep.calls += 1  # 실패한 호출도 유닛을 쓴다
        try:
            return video_ids(youtube_api.fetch_playlist(prefix + channel_id[2:], api_key, get,
                                                        max_results=config.SHORTS_PLAYLIST_RESULTS, part="contentDetails"))
        except youtube_api.PlaylistNotFound:
            return set()  # 그 탭 재생목록이 없는 채널 = 그 탭에 영상이 없다

    for channel_id, (channel, its) in groups.items():
        rep.channels += 1
        try:
            shorts = fetch(config.SHORTS_PLAYLIST_PREFIX, channel_id)
            rest = [it for it in its if it["yt"] not in shorts]
            longs = fetch(config.LONG_PLAYLIST_PREFIX, channel_id) if rest else set()  # 전부 쇼츠로 확인됐으면 UULF는 부르지 않는다
        except (youtube_api.QuotaExceeded, youtube_api.KeyRejected) as e:
            rep.aborted = str(e)  # 상태·reason만 담긴다
            log.warning("쇼츠 판별 중단 — %s (다음 실행에 다시 시도합니다)", e)
            break
        except youtube_api.ApiError as e:
            rep.failed_channels += 1
            log.warning("쇼츠 판별: %s 조회 실패 — %s (다음 실행에 다시 시도합니다)", channel.source, e)
            continue
        # 필요한 목록을 모두 읽었다 → 값을 정한다 (여기까지 오지 못하면 이 채널의 항목은 하나도 바뀌지 않는다)
        for it in its:
            if it["yt"] in shorts:
                it["short"] = True
                rep.short += 1
            elif it["yt"] in longs:
                it["short"] = False
                rep.long += 1
            elif _aged(it, now):
                it["short"] = False
                rep.confirmed_long += 1
    rep.undecided = sum(1 for it in pending if "short" not in it)  # 값이 정해지지 않은 채 남은 항목 (다음 실행에 다시 시도)
    return rep
