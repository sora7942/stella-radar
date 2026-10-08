"""디스코드 웹훅 알림 (SPEC 7장): 알림 1건 = 임베드 1개, 한 메시지에 10개, 실행당 최대 2메시지(20건), 넘치면 "외 N건".

**웹훅 URL은 비밀이다.** 어디에도 출력·로그로 남기지 않는다. requests 예외의 메시지에는 URL이 들어 있으므로
(`... for url: https://discord.com/api/webhooks/<id>/<token>`) 발송 실패는 예외 종류와 HTTP 상태만 기록한다.
"""
from __future__ import annotations

import logging
import time

import requests

from . import config, http

log = logging.getLogger(__name__)

KIND_LABEL = {"live": "방송 시작", "video": "영상", "notice": "공지", "music": "음악"}
SHORT_LABEL = "쇼츠"  # 알림 시점에 short가 true인 영상은 '영상' 대신 이 라벨을 쓴다 (판별 전이면 '영상')
GROUP_ALL_LABEL = "스텔라이브"
_MAX_NAMES = 3  # 이름이 이보다 많으면 "A, B, C 외 N명"
_TITLE_LIMIT = 256  # 디스코드 임베드 제목 한도
_AUTHOR_LIMIT = 256


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def names_of(who: list[str], members: dict) -> str:
    """who 태그 → 표시 이름. 멤버 이름 / 그룹 이름 / all → 스텔라이브. 알 수 없으면 스텔라이브."""
    people = members.get("members", {})
    groups = {g["key"]: g["label"] for g in members.get("groups", [])}
    labels = []
    for key in who:
        if key == "all":
            labels.append(GROUP_ALL_LABEL)
        elif key in people:
            labels.append(people[key]["n"])
        elif key in groups:
            labels.append(groups[key])
    if not labels:
        return GROUP_ALL_LABEL
    if len(labels) > _MAX_NAMES:
        return ", ".join(labels[:_MAX_NAMES]) + f" 외 {len(labels) - _MAX_NAMES}명"
    return ", ".join(labels)


def color_of(who: list[str], members: dict) -> int:
    """첫 번째로 찾은 멤버의 색(#RRGGBB → int). 멤버가 없으면(그룹·단체) 기본색."""
    people = members.get("members", {})
    for key in who:
        color = (people.get(key) or {}).get("c")
        if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
            try:
                return int(color[1:], 16)
            except ValueError:
                pass
    return config.DISCORD_DEFAULT_COLOR


def build_embed(alert: dict, members: dict) -> dict:
    names = names_of(alert["who"], members)
    label = alert.get("cat") if alert["kind"] == "notice" and alert.get("cat") else KIND_LABEL[alert["kind"]]
    if alert["kind"] == "video" and alert.get("short") is True:
        label = SHORT_LABEL
    embed = {
        "author": {"name": _clip(f"{names} · {label}", _AUTHOR_LIMIT)},
        "title": _clip(alert.get("title") or f"{names} 방송 시작", _TITLE_LIMIT),
        "color": color_of(alert["who"], members),
    }
    if alert.get("url"):
        embed["url"] = alert["url"]
    if alert.get("yt"):
        embed["thumbnail"] = {"url": config.YOUTUBE_THUMBNAIL_URL.format(video_id=alert["yt"])}
    date = alert.get("date")
    if date and len(date) > 10:  # 날짜만 있는 값은 시각이 없으니 타임스탬프를 달지 않는다
        embed["timestamp"] = date
    return embed


def build_messages(alerts: list[dict], members: dict, *, site_url: str) -> list[dict]:
    """알림 목록 → 웹훅 페이로드 목록. 알림이 없으면 빈 리스트. 상한을 넘으면 마지막 메시지에 "외 N건"을 붙인다."""
    per, cap = config.DISCORD_EMBEDS_PER_MESSAGE, config.DISCORD_EMBEDS_PER_MESSAGE * config.DISCORD_MAX_MESSAGES
    shown = [build_embed(a, members) for a in alerts[:cap]]
    messages = [
        {"embeds": shown[i : i + per], "allowed_mentions": {"parse": []}}  # 제목에 @everyone이 있어도 멘션이 걸리지 않게
        for i in range(0, len(shown), per)
    ]
    if len(alerts) > cap:
        messages[-1]["content"] = f"외 {len(alerts) - cap}건 더 있어요 → {site_url}"
    return messages


def format_dry_run(messages: list[dict]) -> str:
    """보낼 내용을 사람이 읽는 글로. 실제 페이로드에서 만들기 때문에 여기 보이는 것이 곧 보낼 내용이다 (웹훅 URL은 없다)."""
    total = sum(len(m["embeds"]) for m in messages)
    lines = [f"[디스코드 dry-run] 알림 {total}건 → 메시지 {len(messages)}개 (보내지 않음)"]
    for i, msg in enumerate(messages, 1):
        lines.append(f"  메시지 {i}/{len(messages)} · 임베드 {len(msg['embeds'])}개")
        for n, e in enumerate(msg["embeds"], 1):
            lines.append(f"   {n:>2}. {e['author']['name']}")
            lines.append(f"       제목: {e['title']}")
            extra = [f"색 #{e['color']:06X}"]
            if "timestamp" in e:
                extra.append(f"시각 {e['timestamp']}")
            if "thumbnail" in e:
                extra.append(f"썸네일 {e['thumbnail']['url']}")
            lines.append("       " + " · ".join(extra))
            lines.append(f"       링크: {e.get('url', '(없음)')}")
        if "content" in msg:
            lines.append(f"       본문: {msg['content']}")
    return "\n".join(lines)


def _retry_after(response) -> float | None:
    """429 응답의 대기 시간(초). 읽을 수 없으면 None."""
    try:
        value = response.json().get("retry_after")
    except (ValueError, AttributeError):
        value = None
    if value is None and response is not None:
        value = response.headers.get("Retry-After")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _post_one(webhook_url: str, message: dict, post, sleep) -> bool:
    for attempt in (1, 2):
        try:
            post(webhook_url, message)
            return True
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429 and attempt == 1:
                wait = _retry_after(e.response)
                if wait is not None and wait <= config.DISCORD_RETRY_AFTER_MAX:
                    log.info("디스코드 속도 제한(429) — %.1f초 뒤 한 번 더 시도", wait)
                    sleep(wait)
                    continue
            log.warning("디스코드 발송 실패: HTTP %s", status)  # 예외 메시지에는 웹훅 URL이 들어 있어 남기지 않는다
            return False
        except requests.RequestException as e:
            log.warning("디스코드 발송 실패: %s", type(e).__name__)
            return False
    return False


def send(webhook_url: str, messages: list[dict], *, post=http.post_json, sleep=time.sleep) -> tuple[int, int]:
    """메시지를 차례로 보낸다 → (성공, 실패) 메시지 수. 하나가 실패해도 다음 메시지는 시도한다. 예외로 끝나지 않는다."""
    sent = failed = 0
    for i, message in enumerate(messages):
        if i:
            sleep(config.DISCORD_MESSAGE_DELAY)
        if _post_one(webhook_url, message, post, sleep):
            sent += 1
        else:
            failed += 1
    return sent, failed
