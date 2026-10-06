"""비밀 값(API 키·웹훅 URL)이 로그에 섞여 나가지 않게 하는 마지막 방어선.

1차 방어는 '비밀을 메시지에 넣지 않는 것'이다(키는 헤더로만 보내고, 오류는 상태 코드·사유만 기록한다).
이 모듈은 그래도 어떤 경로로든 로그 문자열에 비밀이 들어갔을 때 출력 직전에 가린다 (예외 traceback 포함).
"""
from __future__ import annotations

import logging

_MIN_LENGTH = 8  # 너무 짧은 값은 일반 단어를 가릴 수 있어 등록하지 않는다
_secrets: set[str] = set()
MASK = "***"


def register(secret: str | None) -> None:
    """이 값이 로그 출력에 나타나면 가린다."""
    if secret and len(secret.strip()) >= _MIN_LENGTH:
        _secrets.add(secret.strip())


def clear() -> None:
    _secrets.clear()


def mask(text: str) -> str:
    for secret in sorted(_secrets, key=len, reverse=True):  # 긴 값부터
        text = text.replace(secret, MASK)
    return text


class RedactingFormatter(logging.Formatter):
    """완성된 로그 줄(메시지 + traceback)에서 등록된 비밀을 가린다."""

    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


def configure_logging(level: int = logging.INFO) -> None:
    """main.py·send_alerts.py 공용 로깅 설정. 이미 핸들러가 있으면(예: pytest) 건드리지 않는다."""
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    logging.basicConfig(level=level, handlers=[handler])
