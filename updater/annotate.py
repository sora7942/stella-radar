"""GitHub Actions 실행 요약에 보이는 `::warning::` 주석. Actions가 아닌 곳(로컬·테스트)에서는 아무것도 출력하지 않는다.

로그에 묻히는 일반 경고와 달리 실행 요약(Annotations)에 올라오므로, 사람이 조치해야 하는 일(예: API 키 확인, Secret 미등록)에 쓴다.
메시지에는 비밀이 들어가면 안 된다. 그래도 등록된 비밀은 출력 직전에 가린다.
"""
from __future__ import annotations

from . import redact


def _escape(text: str, *, prop: bool = False) -> str:
    """워크플로 명령 형식의 이스케이프 (줄바꿈이나 '%'가 명령을 깨뜨리지 않게)."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def warning(title: str, message: str, *, environ) -> bool:
    """Actions(GITHUB_ACTIONS=true)에서만 주석을 출력한다. 출력했으면 True."""
    if environ.get("GITHUB_ACTIONS") != "true":
        return False
    print(f"::warning title={_escape(title, prop=True)}::{_escape(redact.mask(message))}", flush=True)
    return True
