"""치지직 live-status → 멤버별 방송 상태 (SPEC 5장). 비공식 API라 언제든 막힐 수 있다.

- `content.status == "OPEN"`이면 방송 중. 닫힌 상태도 content가 채워져 오므로 OPEN만 본다
- `openDate`는 오프셋 없는 KST 문자열 → since를 +09:00으로 변환한다
- **요청이 실패한 멤버의 패치에는 `live`를 넣지 않는다.** 그러면 이전 live 값이 그대로 남는다 — 실패를 '방송 꺼짐'으로 저장하면
  다음 성공 때 off→on으로 보여서 이미 알린 방송 시작 알림이 또 나간다
- 실패한 멤버는 `liveFails`(연속 실패 실행 수)만 올린다. 성공하면 0으로 되돌려 병합 단계(state.merge_status)가 필드를 지운다.
  연속 실패가 CHZZK_FAIL_WARN_STREAK에 닿으면 호출자가 준 on_streak로 알린다 (Actions 주석 등)
- HTTP 5xx면 다음 후보 엔드포인트(config.CHZZK_LIVE_STATUS_URLS: v2 → v3)로 바로 넘어간다. 후야 방송이 Actions(해외 IP)에서 v2만
  HTTP 500 code 9004("해외 시청 불가능한 컨텐츠")로 막혔고 v3는 통과했다. 후보가 전부 5xx면 1초 뒤 후보 전체를 CHZZK_RETRY_5XX번 더 돈다.
  4xx·연결 오류·응답 형식 오류는 넘어가지 않는다
- chzzk_id가 없는 멤버는 건너뛴다
"""
from __future__ import annotations

import logging
import time

import requests

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


def _api_code(response) -> int | None:
    """오류 응답 본문 {"code": 9004, …}의 정수 code. 읽을 수 없으면 None. 메시지·본문은 돌려주지 않는다."""
    try:
        code = response.json().get("code")
    except Exception:
        return None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _fetch(channel_id: str, label: str, *, get, retries: int, retry_delay: float, sleep) -> dict:
    """live-status JSON. 후보 엔드포인트를 앞에서부터 시도하고, HTTP 5xx일 때만 다음 후보로 넘어간다.
    후보가 전부 5xx면 retry_delay초 뒤 후보 전체를 retries번 더 돈다. 그 밖의 오류(4xx·연결·형식)는 바로 던진다."""
    last: requests.HTTPError | None = None
    for round_ in range(retries + 1):
        if round_:
            log.info("치지직 %s: 모든 엔드포인트가 5xx — 재시도 %d/%d", label, round_, retries)
            sleep(retry_delay)
        for template in config.CHZZK_LIVE_STATUS_URLS:
            try:
                return get(template.format(channel_id=channel_id)).json()
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status is None or status < 500:
                    raise
                last = e
                code = _api_code(e.response)
                log.info("치지직 %s: HTTP %d%s — 다음 엔드포인트 시도", label, status, f" (code {code})" if code is not None else "")
    assert last is not None
    raise last


def _reason(e: Exception) -> str:
    """주석·로그에 쓰는 짧은 실패 사유: HTTP 상태(+치지직 code) 또는 예외 종류 (URL·본문은 넣지 않는다)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = _api_code(e.response)
        return f"HTTP {e.response.status_code}" + (f", code {code}" if code is not None else "")
    return type(e).__name__


def _previous_fails(prev_status: dict | None, key: str) -> int:
    value = ((prev_status or {}).get(key) or {}).get("liveFails")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def collect(
    members: dict,
    *,
    now_iso: str,
    prev_status: dict | None = None,
    on_streak=None,
    get=http.get,
    delay: float = config.REQUEST_DELAY,
    sleep=time.sleep,
    retries: int = config.CHZZK_RETRY_5XX,
    retry_delay: float = config.CHZZK_RETRY_DELAY,
) -> tuple[dict, list[str]]:
    """members = members.json의 'members', prev_status = status.json의 이전 'members'(연속 실패 횟수를 읽는다).
    → ({멤버 key: 패치}, 실패 메시지). 패치는
      성공: {"live": {…, "checkedAt": now_iso}}  (이전에 연속 실패 중이었으면 "liveFails": 0도 — 병합 때 필드가 지워진다)
      실패: {"liveFails": 이전+1}                 (live 키 없음 → 이전 live·checkedAt 유지)
    성공한 live에는 확인 시각 checkedAt=now_iso를 붙인다. 사이트는 checkedAt이 오래된 LIVE를 숨기므로,
    요청이 계속 실패하거나 소스가 꺼져 있으면 이전 값(과 오래된 checkedAt)이 남아도 LIVE로 보이지 않는다.
    연속 실패가 CHZZK_FAIL_WARN_STREAK 이상이 되면 on_streak(멤버 이름, 연속 횟수, 사유)를 부른다."""
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
        before = _previous_fails(prev_status, key)
        try:
            doc = _fetch(channel_id, m["n"], get=get, retries=retries, retry_delay=retry_delay, sleep=sleep)
            patch = {"live": {**parse_live(doc, channel_id), "checkedAt": now_iso}}
            if before:
                patch["liveFails"] = 0  # 연속 실패가 끊겼다
                log.info("치지직 %s: 확인 복구 (연속 실패 %d회 뒤)", m["n"], before)
            patches[key] = patch
        except Exception as e:  # 멤버 하나의 실패가 다른 멤버를 막지 않게 한다. 이전 live 값은 그대로 남는다
            msg = f"{m['n']}: {type(e).__name__}: {e}"
            log.warning("치지직 실패 — %s", msg)
            errors.append(msg)
            streak = before + 1
            patches[key] = {"liveFails": streak}
            if streak >= config.CHZZK_FAIL_WARN_STREAK and on_streak is not None:
                on_streak(m["n"], streak, _reason(e))
    return patches, errors
