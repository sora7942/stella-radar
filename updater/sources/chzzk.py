"""치지직 live-status → 멤버별 방송 상태 (SPEC 5장). 비공식 API라 언제든 막힐 수 있다.

- `content.status == "OPEN"`이면 방송 중. 닫힌 상태도 content가 채워져 오므로 OPEN만 본다
- `openDate`는 오프셋 없는 KST 문자열 → since를 +09:00으로 변환한다
- **요청이 실패한 멤버는 결과에 넣지 않는다.** 그러면 이전 live 값이 그대로 남는다 — 실패를 '방송 꺼짐'으로 저장하면
  다음 성공 때 off→on으로 보여서 이미 알린 방송 시작 알림이 또 나간다
- chzzk_id가 없는 멤버는 건너뛴다
"""
from __future__ import annotations

import logging
import time

from .. import config, http, timeutil

log = logging.getLogger(__name__)


class LiveParseError(ValueError):
    """live-status가 예상한 형식이 아니다 (차단·API 변경 등)."""


def parse_live(doc, channel_id: str) -> dict:
    """live-status JSON → {"on": False} 또는 {"on": True, "title", "url", "since"?}."""
    content = doc.get("content") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get("code") != 200 or not isinstance(content, dict):
        raise LiveParseError(f"예상 밖의 응답 형식 (code={doc.get('code') if isinstance(doc, dict) else type(doc).__name__})")
    answered = content.get("channelId")
    if answered and answered != channel_id:  # 다른 채널의 응답을 받으면 상태를 믿을 수 없다
        raise LiveParseError(f"요청한 채널과 응답 채널이 다름: {answered}")
    status = content.get("status")
    if not status:
        raise LiveParseError("content.status가 없음")
    if status != "OPEN":
        return {"on": False}

    live = {
        "on": True,
        "title": (content.get("liveTitle") or "").strip(),
        "url": config.CHZZK_LIVE_PAGE_URL.format(channel_id=channel_id),
    }
    try:
        live["since"] = timeutil.naive_kst_to_iso(content["openDate"])
    except (KeyError, TypeError, ValueError):
        log.warning("치지직 %s: openDate를 읽을 수 없어 since 없이 저장", channel_id)
    return live


def collect(
    members: dict,
    *,
    get=http.get,
    delay: float = config.REQUEST_DELAY,
    sleep=time.sleep,
) -> tuple[dict, list[str]]:
    """members = members.json의 'members'. → ({멤버 key: {"live": …}} (성공한 멤버만), 실패 메시지)."""
    patches: dict[str, dict] = {}
    errors: list[str] = []
    no_id = [k for k, m in members.items() if not m.get("chzzk_id")]
    if no_id:
        log.info("치지직: chzzk_id가 없어 건너뜀: %s", ", ".join(no_id))
    requested = 0
    for key, m in members.items():
        channel_id = m.get("chzzk_id")
        if not channel_id:
            continue
        if requested:
            sleep(delay)
        requested += 1
        try:
            doc = get(config.CHZZK_LIVE_STATUS_URL.format(channel_id=channel_id)).json()
            patches[key] = {"live": parse_live(doc, channel_id)}
        except Exception as e:  # 멤버 하나의 실패가 다른 멤버를 막지 않게 한다. 이전 값은 그대로 남는다
            msg = f"{m['n']}: {type(e).__name__}: {e}"
            log.warning("치지직 실패 — %s", msg)
            errors.append(msg)
    return patches, errors
