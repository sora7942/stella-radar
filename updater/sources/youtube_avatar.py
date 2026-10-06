"""유튜브 채널 페이지 → 멤버 프로필 사진 URL(og:image). 하루에 한 번만 다시 읽는다 (SPEC 5장).

- 이미지를 내려받지 않고 URL만 저장한다 (CLAUDE.md)
- og:image 메타는 지금 `<head>`가 아니라 `</head>` 뒤(body 안)에 있다 → head까지만 잘라서 찾으면 놓친다. 문서 전체의 <meta>를 훑는다
- 한 멤버가 실패하면 그 멤버의 이전 값을 유지하고 나머지는 계속한다. avatarCheckedAt도 그대로라 다음 실행에 다시 시도한다
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import config, http, timeutil

log = logging.getLogger(__name__)

_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)


class AvatarParseError(ValueError):
    """채널 페이지에서 프로필 이미지를 찾지 못했거나, 프로필 이미지로 볼 수 없는 값."""


def parse_avatar(content: bytes) -> str:
    """채널 페이지 HTML → og:image URL. 유튜브 이미지 호스트가 아니면 AvatarParseError."""
    text = content.decode("utf-8", errors="replace")
    url = None
    for tag in _META_TAG.findall(text):
        if "og:image" not in tag:  # 페이지에 <meta>가 수십 개라, 후보만 파싱한다
            continue
        meta = BeautifulSoup(tag, "html.parser").find("meta")
        if meta is not None and meta.get("property") == "og:image":  # og:image:width 등은 제외
            url = (meta.get("content") or "").strip()
            break
    if not url:
        raise AvatarParseError(f"og:image 메타를 찾지 못함 ({len(content)}바이트)")
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in config.AVATAR_HOSTS):
        raise AvatarParseError(f"프로필 이미지가 아닌 og:image: {url[:80]}")
    return url


_SIZE_PARAM = re.compile(r"=s\d+(?=-|\?|$)")


def resize(url: str, size: int = config.AVATAR_SIZE) -> str:
    """yt3 이미지 URL의 크기 파라미터만 바꾼다 (`…=s900-c-k-c0x00ffffff-no-rj` → `…=s240-c-k-c0x00ffffff-no-rj`).
    크기 파라미터가 없는 URL은 그대로 둔다."""
    return _SIZE_PARAM.sub(f"=s{size}", url, count=1)


def is_due(previous: dict, now: datetime) -> bool:
    """이 멤버의 아바타를 지금 다시 읽어야 하나. 값이 없거나 마지막 확인이 AVATAR_REFRESH_HOURS 이상 지났으면 True."""
    checked = previous.get("avatarCheckedAt")
    if not previous.get("avatar") or not checked:
        return True
    try:
        return now - timeutil.parse_kst(checked) >= timedelta(hours=config.AVATAR_REFRESH_HOURS)
    except (ValueError, TypeError):
        return True  # 읽을 수 없는 시각은 확인한 적 없는 것으로 본다


def collect(
    members: dict,
    previous: dict,
    *,
    now: datetime,
    now_iso: str,
    get=http.get,
    delay: float = config.REQUEST_DELAY,
    sleep=time.sleep,
) -> tuple[dict, list[str]]:
    """members = members.json의 'members', previous = status.json의 이전 'members'.
    → ({멤버 key: {"avatar", "avatarCheckedAt"}} (이번에 성공한 멤버만), 실패 메시지)."""
    patches: dict[str, dict] = {}
    errors: list[str] = []
    requested = skipped = 0
    for key, m in members.items():
        if not m.get("yt_id"):
            continue
        if not is_due(previous.get(key, {}), now):
            skipped += 1
            continue
        if requested:
            sleep(delay)
        requested += 1
        try:
            url = resize(parse_avatar(get(config.YOUTUBE_CHANNEL_URL.format(channel_id=m["yt_id"])).content))
            patches[key] = {"avatar": url, "avatarCheckedAt": now_iso}
        except Exception as e:  # 멤버 하나의 실패(네트워크·형식)가 다른 멤버를 막지 않게 한다
            msg = f"{m['n']}: {type(e).__name__}: {e}"
            log.warning("아바타 실패 — %s", msg)
            errors.append(msg)
    log.info("아바타: 요청 %d명 (성공 %d, 실패 %d), %d시간 이내라 건너뜀 %d명",
             requested, len(patches), len(errors), config.AVATAR_REFRESH_HOURS, skipped)
    return patches, errors
