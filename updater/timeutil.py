"""시간은 항상 timezone-aware, 저장은 +09:00 ISO 문자열 (CLAUDE.md)."""
from datetime import date, datetime

from . import config


def now_kst() -> datetime:
    return datetime.now(config.KST)


def to_kst_iso(value: str | datetime) -> str:
    """ISO 문자열(예: UTC '+00:00') 또는 aware datetime → '2026-10-04T15:44:08+09:00'."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError(f"timezone 정보가 없는 시각: {value!r}")
    return dt.astimezone(config.KST).isoformat(timespec="seconds")


def parse_kst(value: str) -> datetime:
    """저장된 date 값을 비교용 aware datetime으로. 'YYYY-MM-DD'는 그날 00:00 KST."""
    if len(value) == 10:
        d = date.fromisoformat(value)
        return datetime(d.year, d.month, d.day, tzinfo=config.KST)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=config.KST)
