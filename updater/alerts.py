"""알림 대상 판정 (SPEC 7장). 전부 순수 함수다 — 네트워크·파일을 건드리지 않는다.

입력은 '이번 실행에서 처음 본' 항목뿐이다(state.merge_news가 돌려주는 fresh, 그리고 이전/새 status). 이미 알린 항목이 다시
나오지 않는 것은 병합이 보장하고, 여기서는 '새로 본 것 중 알릴 만한 것'만 고른다.

규칙 (값은 config.py):
- 영상(yt-)   : 게시 시각이 ALERT_VIDEO_HOURS 이내
- 공지(sl-)   : 날짜가 ALERT_NOTICE_DAYS 이내 (달력 기준 — 공지는 날짜만 있다)
- 새 곡(mu-)  : 발매일이 MUSIC_ALERT_DAYS 이내 (달력 기준)
- 방송 시작   : 새 since가 이전에 저장된 since와 다를 때만 새 방송. 같은 since면 확인 공백이 길었어도 알리지 않는다.
                단, since가 ALERT_LIVE_MAX_AGE_HOURS보다 오래됐으면 늦은 알림이라 알리지 않는다.
                since가 없으면(또는 읽을 수 없으면) 이전 규칙: 꺼짐→켜짐일 때만
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import config, timeutil

log = logging.getLogger(__name__)

# 알림 종류 → 정렬 순서. 한 번에 20건을 넘으면 뒤가 잘리므로 급한 것(방송, 공지)이 앞에 오게 한다
KIND_ORDER = {"live": 0, "notice": 1, "music": 2, "video": 3}
_KIND_BY_PREFIX = {"yt": "video", "sl": "notice", "mu": "music"}


def _days_ago(date_str: str, now: datetime) -> int:
    """달력 기준으로 며칠 전인가 (KST 날짜끼리). 날짜만 있는 값('2026-10-05')도 같은 방식으로 다룬다."""
    return (now.astimezone(config.KST).date() - timeutil.parse_kst(date_str).astimezone(config.KST).date()).days


def _within(kind: str, date_str: str, now: datetime) -> bool:
    if kind == "video":
        return now - timeutil.parse_kst(date_str) <= timedelta(hours=config.ALERT_VIDEO_HOURS)
    if kind == "notice":
        return _days_ago(date_str, now) <= config.ALERT_NOTICE_DAYS
    return _days_ago(date_str, now) <= config.MUSIC_ALERT_DAYS  # music


def news_alerts(fresh: list[dict], now: datetime) -> list[dict]:
    """이번에 처음 본 news 항목 → 알릴 항목. 미래 날짜(예정 프리미어 등)는 새로 보인 것이므로 알린다."""
    out = []
    for it in fresh:
        kind = _KIND_BY_PREFIX.get(str(it.get("id", "")).split("-", 1)[0])
        if kind is None:  # 알 수 없는 종류는 알리지 않는다
            continue
        try:
            if not _within(kind, it["date"], now):
                continue
        except (KeyError, ValueError, TypeError):
            log.warning("날짜를 읽을 수 없어 알림에서 제외: %s", it.get("id"))
            continue
        out.append({
            "kind": kind, "cat": it.get("cat"), "who": list(it.get("who") or []), "title": it.get("title") or "",
            "url": it.get("url"), "date": it["date"], "yt": it.get("yt"),
            "short": it.get("short"),  # True면 임베드에 '쇼츠'로 표시. 아직 판별 전이면 None(표시 없음)
        })
    return out


def _parse_since(value) -> datetime | None:
    """since → aware datetime. 없거나 읽을 수 없으면 None(= since 없음으로 취급)."""
    if not value or not isinstance(value, str):
        return None
    try:
        return timeutil.parse_kst(value)
    except (ValueError, TypeError):
        return None


def live_alerts(prev_members: dict, new_members: dict, now: datetime) -> list[dict]:
    """이전/새 status의 members → 방송 시작 알림. 모듈 설명의 방송 시작 규칙을 그대로 따른다.

    확인에 실패한 멤버는 새 status에도 이전 live가 그대로 있으므로(같은 since, 켜져 있던 채로) 알림이 나지 않는다."""
    out = []
    for key, entry in new_members.items():
        live = (entry or {}).get("live") or {}
        if not live.get("on"):
            continue
        before = ((prev_members.get(key) or {}).get("live")) or {}  # 이전 항목이 없으면 꺼져 있던 것으로 본다
        since = _parse_since(live.get("since"))
        if since is not None:
            if since == _parse_since(before.get("since")):
                continue  # 같은 방송. 확인 공백이 얼마나 길었든 다시 알리지 않는다
            if now - since > timedelta(hours=config.ALERT_LIVE_MAX_AGE_HOURS):
                continue  # 늦은 알림 방지
        elif before.get("on"):
            continue  # since가 없을 때의 이전 규칙: 꺼짐→켜짐만
        out.append({
            "kind": "live", "cat": "방송", "who": [key], "title": (live.get("title") or "").strip(),
            "url": live.get("url"), "date": live.get("since") if since is not None else None, "yt": None,
        })
    return out


def _sort_key(alert: dict):
    date = alert.get("date")
    try:
        when = timeutil.parse_kst(date) if date else timeutil.parse_kst("1970-01-01")
    except (ValueError, TypeError):
        when = timeutil.parse_kst("1970-01-01")
    return (KIND_ORDER[alert["kind"]], -when.timestamp())


def build_alerts(fresh_news: list[dict], prev_members: dict, new_members: dict, now: datetime) -> list[dict]:
    """방송 → 공지 → 새 곡 → 영상 순, 같은 종류 안에서는 최신순."""
    return sorted(live_alerts(prev_members, new_members, now) + news_alerts(fresh_news, now), key=_sort_key)
