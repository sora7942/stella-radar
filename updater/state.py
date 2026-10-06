"""이전 상태 불러오기, 병합·중복 제거·정렬·자르기, JSON 쓰기.

이전 상태(SPEC 6장)는 배포된 사이트에서 읽는다. 읽기 규칙(사용자 확정):
- 404(아직 배포 전)만 저장소 파일로 대체한다
- 타임아웃·5xx·JSON/형식 오류는 재시도 후에도 실패하면 StateLoadError — 시드로 되돌아가면 누적 데이터가 초기화되고
  `added`·디스코드 알림이 중복되기 때문에, 이 경우 실행을 실패시켜 배포를 건너뛴다(기존 사이트 유지)
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
from pathlib import Path

import requests

from . import config, http, timeutil

log = logging.getLogger(__name__)

# 일시적일 수 있어 재시도하는 4xx
_RETRYABLE_4XX = {408, 429}


class StateLoadError(RuntimeError):
    """이전 상태를 믿을 수 있게 읽지 못했다. 이때 계속 진행하면 데이터가 망가질 수 있다."""


# ---------------------------------------------------------------- JSON 입출력
def read_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, data: dict) -> None:
    """UTF-8, ensure_ascii=False. 임시 파일에 쓴 뒤 교체해서 중간에 실패해도 원본이 남는다."""
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"  # 직렬화 실패는 파일을 건드리기 전에 난다
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- 이전 상태
def _list_key(name: str) -> str:
    return "members" if name == "status" else "items"


def default_doc(name: str) -> dict:
    return {"updatedAt": None, _list_key(name): {} if name == "status" else []}


def _validate(name: str, doc) -> dict:
    key = _list_key(name)
    expected = dict if name == "status" else list
    if not isinstance(doc, dict) or not isinstance(doc.get(key), expected):
        raise ValueError(f"{name}.json 형식이 올바르지 않음 ('{key}'가 {expected.__name__}이어야 함)")
    return doc


def _read_local(name: str, path: Path) -> dict:
    if not path.exists():
        log.info("%s: 로컬 파일 없음 → 빈 상태로 시작", name)
        return default_doc(name)
    try:
        return _validate(name, read_json(path))
    except ValueError as e:  # JSONDecodeError 포함
        raise StateLoadError(f"저장소의 {path.name}을 읽을 수 없음: {e}") from e


def load_previous(
    name: str,
    *,
    site_url: str | None = None,
    local_dir: Path | str = config.DATA_DIR,
    get=http.get,
    sleep=time.sleep,
    now=time.time,
    local_only: bool = False,
) -> dict:
    """name = news | catalog | status. 규칙은 모듈 설명 참고."""
    local_path = Path(local_dir) / f"{name}.json"
    if local_only:
        return _read_local(name, local_path)

    base = site_url or config.site_url()
    if not base.endswith("/"):
        base += "/"
    url = f"{base}data/{name}.json?t={int(now())}"  # ?t= 로 캐시 회피

    delay = config.STATE_LOAD_BACKOFF
    last: Exception | None = None
    for attempt in range(1, config.STATE_LOAD_ATTEMPTS + 1):
        try:
            return _validate(name, json.loads(get(url).content))
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 404:
                log.info("%s: 배포본 없음(404) → 저장소 파일 사용", name)
                return _read_local(name, local_path)
            if status is not None and 400 <= status < 500 and status not in _RETRYABLE_4XX:
                raise StateLoadError(f"{name}.json 읽기 실패: HTTP {status}") from e
            last = e
        except (requests.RequestException, ValueError) as e:  # 연결·타임아웃·JSON/형식 오류
            last = e
        if attempt < config.STATE_LOAD_ATTEMPTS:
            log.warning("%s: 이전 상태 읽기 실패 (%d/%d) %s — 재시도", name, attempt, config.STATE_LOAD_ATTEMPTS, last)
            sleep(delay)
            delay *= 2
    raise StateLoadError(f"{name}.json 읽기 실패 ({config.STATE_LOAD_ATTEMPTS}회 시도): {last}") from last


# ---------------------------------------------------------------- 병합
def _sort_key(it: dict):
    try:
        return timeutil.parse_kst(it["date"])
    except (KeyError, ValueError, TypeError):
        log.warning("날짜를 읽을 수 없는 항목: %s", it.get("id"))
        return timeutil.parse_kst("1970-01-01")


def merge_news(
    previous: list[dict], new_items: list[dict], *, now_iso: str, limit: int = config.NEWS_MAX_ITEMS
) -> tuple[list[dict], list[dict]]:
    """이전 항목 + 이번 수집분 → (date 내림차순, 최대 limit개, 이번에 처음 본 항목들).

    - id가 같으면 기존 항목이 이긴다(제목·who·added 포함). added는 처음 발견한 시각에서 절대 바꾸지 않는다
    - 새 항목은 added=now_iso. 잘려 나간 새 항목도 '이번에 처음 본 항목'에는 포함한다
    """
    by_id: dict[str, dict] = {}
    for it in previous:
        by_id.setdefault(it["id"], it)

    fresh: list[dict] = []
    for it in new_items:
        if it["id"] in by_id:
            continue
        entry = copy.deepcopy(it)
        entry["added"] = now_iso
        by_id[entry["id"]] = entry
        fresh.append(entry)

    merged = sorted(by_id.values(), key=lambda it: (_sort_key(it), it["id"]), reverse=True)
    return merged[:limit], fresh


_STATUS_FIELD_ORDER = ("avatar", "avatarCheckedAt", "live", "uploads")  # uploads: 유튜브 업로드 재생목록 ID 캐시 (YouTube API)


def merge_status(previous: dict, patches: dict) -> dict:
    """status.json의 members에 소스별 패치({멤버 key: {필드: 값}})를 반영한 새 dict.
    패치에 없는 멤버·필드는 이전 값 그대로다 — 소스가 실패한 멤버는 패치가 없으므로 이전 값이 유지된다.
    필드 순서는 고정해서 값이 같으면 파일도 같게 나온다."""
    merged = copy.deepcopy(previous)
    for key, patch in patches.items():
        merged.setdefault(key, {}).update(copy.deepcopy(patch))

    def ordered(fields: dict) -> dict:
        rank = lambda f: (_STATUS_FIELD_ORDER.index(f) if f in _STATUS_FIELD_ORDER else len(_STATUS_FIELD_ORDER), f)
        return {f: fields[f] for f in sorted(fields, key=rank)}

    return {key: ordered(fields) for key, fields in merged.items()}


def _catalog_key(it: dict):
    num = it["id"]
    return (it.get("date") or "", int(num) if str(num).isdigit() else -1, str(num))


def merge_catalog(previous: list[dict], new_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """catalog 병합 → (date 내림차순·같은 날짜는 번호(숫자) 큰 순, 이번에 처음 들어온 항목들). 자르지 않는다.
    id가 같으면 기존 항목이 이긴다 — 이미 받은 곡은 다시 받지 않으므로 한 번 정해진 값을 유지한다."""
    by_id: dict[str, dict] = {}
    for it in previous:
        by_id.setdefault(it["id"], it)
    fresh: list[dict] = []
    for it in new_items:
        if it["id"] in by_id:
            continue
        entry = copy.deepcopy(it)
        by_id[entry["id"]] = entry
        fresh.append(entry)
    return sorted(by_id.values(), key=_catalog_key, reverse=True), fresh
