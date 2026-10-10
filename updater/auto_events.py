"""공지에서 뽑은 자동 일정 (기능 3, SPEC-v1.1): 대상 선정 → 본문 → Claude → 검증 → 중복 제거 → 저장 상태(auto_events.json).

저장 형식 (site/data/auto_events.json — news·catalog·status처럼 배포본에서 이전 상태를 읽는다):
    {"updatedAt": "...", "processed": {"sl-13905": {"at": "...", "result": "events|none|no_text|error", "tries": 1}},
     "items": [{"id": "auto-sl-13905-1", "source": "sl-13905", "kind": "popup", "title": "...", "start": "2026-10-23", "end": "2026-11-01",
                "time": "10:00–20:00", "place": "...", "who": ["all"], "url": "https://stellive.me/news/13905"}]}

규칙
- 대상: processed에 없는 공지(sl-*) 중 공지 날짜가 오늘부터 45일 이내인 것. **오래된 공지(공지 번호 오름차순)부터** 실행당 최대 5건 (error 재시도도 5건에 포함).
  원 공지가 먼저 처리돼야 같은 일정을 다시 말하는 뒤 공지(FAQ 등)가 중복으로 걸러지고 원 공지의 일정이 남는다 (사용자 결정 2026-10-09). 대신 첫 백필 때는
  새 공지가 밀린 공지 뒤에 처리된다
  error는 모델 출력이 깨졌을 때(JSON 재시도까지 실패)와 상세 페이지가 4xx이거나 본문 컨테이너를 못 찾았을 때만 센다 — 최대 3회까지 재시도한다.
  `no_text`(본문 50자 미만, 포스터 이미지뿐)는 API를 부르지 않고 재시도도 없다. `none`·`events`도 다시 처리하지 않는다
- **API 오류(키 거부·4xx·429·5xx·네트워크)와 상세 페이지의 일시 오류(5xx·네트워크)는 processed에 기록하지 않는다.** 그래야 키 문제나 장애 동안 공지들의
  재시도 횟수가 소진되지 않는다. API 오류가 나면 이 실행의 남은 공지는 부르지 않고 멈춘다
- 검증 (실패한 항목은 버리고 로그, 공지당 최대 5개): kind 목록, 제목 1~60자, start가 공지 날짜 −7일~+365일, end ≥ start(그리고 start+366일 이내),
  who의 key가 하나라도 유효하지 않거나 비면 공지 제목을 tagging으로 태깅한 값. 자동 일정의 url은 모델 출력이 아니라 공지 URL이다
- **자동 일정끼리 중복 제거 (사용자 결정 2026-10-09, 저장 시점에 적용)**: 다른 공지에서 나온 일정끼리 start·end가 같고 (정규화한 제목[`match_title`: 흔한 단어·4자리 연도를 뺀 것, 2026-10-10]이 한쪽을 포함하거나,
  popup·concert·reservation·broadcast는 kind가 같으면 — goods·other는 kind만으로는 합치지 않는다) **먼저 처리된 공지의 일정 하나만 남긴다**(먼저 저장된 것이 이기고, 이번 실행에서는 처리 순서 = 공지 번호 오름차순). 버려진 일정은 저장되지 않으므로 알림도 나가지 않는다.
  같은 공지 안의 일정끼리는 이 규칙을 적용하지 않고, 완전히 같은 것(kind·제목·start·end)만 하나로 합친다
- 보관: 끝난 지 30일 넘은 자동 일정 삭제, processed는 90일 지난 기록 삭제
"""
from __future__ import annotations

import copy
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

from . import config, tagging, timeutil
from .sources import claude_events, stellive_notice_detail

log = logging.getLogger(__name__)

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?\s*(Z|[+-]\d{2}:?\d{2})?")
_CONTROL = re.compile("[\x00-\x1f\x7f\u200b\u200c\u200d\ufeff]")  # 제어·제로폭 문자
_NOTICE_ID = re.compile(r"sl-(\d+)")
_ITEM_FIELDS = ("id", "source", "kind", "title", "start", "end", "time", "place", "who", "url")  # 저장할 때 필드 순서


# ---------------------------------------------------------------- 날짜·문자열
@dataclass(frozen=True)
class When:
    iso: str  # 저장 형식: 날짜만이면 'YYYY-MM-DD', 시각이 있으면 'YYYY-MM-DDTHH:MM:SS+09:00'
    day: date  # KST 날짜
    timed: bool
    at: datetime  # aware. 날짜만이면 그날 00:00 KST


def parse_when(value) -> When:
    """모델이 낸 start·end → When. 날짜만 / 시각 포함(오프셋이 없으면 KST, 있으면 KST로 변환)만 받는다. 그 밖에는 ValueError."""
    if not isinstance(value, str):
        raise ValueError("문자열이 아님")
    v = value.strip()
    if _DATE_ONLY.fullmatch(v):
        d = date.fromisoformat(v)
        return When(d.isoformat(), d, False, datetime(d.year, d.month, d.day, tzinfo=config.KST))
    m = _DATETIME.fullmatch(v)
    if not m:
        raise ValueError("날짜 형식이 아님")
    day, hh, mm, ss, tz = m.groups()
    base = f"{day}T{hh}:{mm}:{ss or '00'}"
    if tz:
        tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        dt = datetime.fromisoformat(base + tz)
    else:
        dt = datetime.fromisoformat(base).replace(tzinfo=config.KST)
    dt = dt.astimezone(config.KST)
    return When(dt.isoformat(timespec="seconds"), dt.date(), True, dt)


def clean_text(value, limit: int) -> str | None:
    """문자열 필드 정리: 제어·제로폭 문자 제거, 공백 정리. 문자열이 아니거나 비었거나 limit을 넘으면 None."""
    if not isinstance(value, str):
        return None
    text = " ".join(_CONTROL.sub(" ", value).split())
    return text if 0 < len(text) <= limit else None


def norm_title(text: str) -> str:
    """제목 비교용: NFKC·소문자·글자와 숫자만 (공백·기호 제거). 사이트의 정규화와 같은 규칙이다."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


_YEAR = re.compile(r"(^|[^0-9])(?:19|20)[0-9]{2}(?![0-9])")  # 4자리 연도. 앞뒤가 숫자면(날짜 덩어리 20261023 등) 연도가 아니다. 사이트와 같은 모양(lookbehind 없이)
_STOPWORDS = re.compile("|".join(re.escape(w) for w in sorted(config.EVENT_TITLE_STOPWORDS, key=len, reverse=True)))


def match_title(text: str) -> str:
    """중복 판정(제목 포함 비교)용 제목: norm_title에 더해 4자리 연도와 흔한 단어(굿즈·판매·마감·예약·오픈·안내·공지)를 뺀다.
    "…스탠드 굿즈 판매 마감"과 "…스탠드 판매 마감"을 같게 보려는 것이다. 다 빠져 빈 문자열이면 호출하는 쪽이 '포함'을 따지지 않는다.
    같은 공지 안의 '완전히 같은 일정' 판정에는 쓰지 않는다(그건 norm_title) — 거기서는 서로 다른 일정을 합치면 안 된다."""
    spaced = "".join(ch if ch.isalnum() else " " for ch in unicodedata.normalize("NFKC", text).lower())
    return _STOPWORDS.sub("", "".join(_YEAR.sub(r"\1 ", spaced).split()))


def valid_who_keys(members: dict) -> set[str]:
    """who에 쓸 수 있는 key: 멤버, 그룹(강지 'boss' 제외 — 강지는 멤버 kangji), all."""
    return set(members["members"]) | {g["key"] for g in members.get("groups", []) if g["key"] != "boss"} | {tagging.ALL}


# ---------------------------------------------------------------- 검증
@dataclass
class Validated:
    events: list = field(default_factory=list)
    dropped: int = 0  # 검증에서 버린 후보 수 (공지당 상한 초과 포함)


def validate_events(raw: list, *, notice_id: str, notice_title: str, notice_day: date, members: dict, index: tagging.TagIndex) -> Validated:
    """모델 출력의 일정 후보 → 검증을 통과한 일정(id·source·url 전). 통과 못 한 후보는 버리고 사유만 로그."""
    out = Validated()
    valid_who = valid_who_keys(members)
    lo = notice_day + timedelta(days=config.EVENT_START_MIN_DAYS)
    hi = notice_day + timedelta(days=config.EVENT_START_MAX_DAYS)
    seen: set[tuple] = set()

    def drop(reason: str) -> None:
        out.dropped += 1
        log.warning("일정 후보를 버림 (%s): %s", notice_id, reason)

    for cand in raw:
        if not isinstance(cand, dict):
            drop("객체가 아님")
            continue
        kind = cand.get("kind").strip().lower() if isinstance(cand.get("kind"), str) else None
        if kind not in config.EVENT_KINDS:
            drop("알 수 없는 kind")
            continue
        title = clean_text(cand.get("title"), config.EVENT_TITLE_MAX)
        if title is None:
            drop(f"제목이 없거나 {config.EVENT_TITLE_MAX}자를 넘음")
            continue
        try:
            start = parse_when(cand.get("start"))
        except ValueError as e:
            drop(f"start를 읽을 수 없음 ({e})")
            continue
        if not lo <= start.day <= hi:
            drop("start가 공지 날짜 기준 허용 범위 밖")
            continue
        end_iso = None
        if cand.get("end") not in (None, ""):
            try:
                end = parse_when(cand.get("end"))
            except ValueError as e:
                drop(f"end를 읽을 수 없음 ({e})")
                continue
            if end.day < start.day or (start.timed and end.timed and end.at < start.at):
                drop("end가 start보다 앞섬")
                continue
            if (end.day - start.day).days > config.EVENT_MAX_SPAN_DAYS:
                drop("start와 end 간격이 너무 큼")
                continue
            if not (end.iso == start.iso or (not end.timed and end.day == start.day)):  # 하루짜리·같은 시각이면 end를 두지 않는다 (중복 판정을 일관되게)
                end_iso = end.iso
        who = cand.get("who")
        if not (isinstance(who, list) and who and all(isinstance(w, str) and w in valid_who for w in who)):
            who = tagging.tag_text(notice_title, index)  # key가 하나라도 틀리면 공지 제목 태깅으로 대체
        who = list(dict.fromkeys(who))
        event = {"kind": kind, "title": title, "start": start.iso}
        if end_iso:
            event["end"] = end_iso
        for name, limit in (("time", config.EVENT_TIME_MAX), ("place", config.EVENT_PLACE_MAX)):
            text = clean_text(cand.get(name), limit) if cand.get(name) not in (None, "") else None
            if text:
                event[name] = text
        event["who"] = who
        key = (kind, norm_title(title), event["start"], event.get("end"))
        if key in seen:  # 같은 공지 안의 완전히 같은 일정
            drop("같은 공지 안의 같은 일정")
            continue
        seen.add(key)
        out.events.append(event)
    if len(out.events) > config.EVENTS_PER_NOTICE:
        drop_n = len(out.events) - config.EVENTS_PER_NOTICE
        out.dropped += drop_n
        log.warning("일정 후보 %d개 중 앞 %d개만 씁니다 (%s)", len(out.events), config.EVENTS_PER_NOTICE, notice_id)
        out.events = out.events[: config.EVENTS_PER_NOTICE]
    return out


# ---------------------------------------------------------------- 자동 일정끼리 중복 제거
def is_duplicate(a: dict, b: dict) -> bool:
    """start·end가 같고 (정규화한 제목이 한쪽을 포함하거나, popup·concert·reservation·broadcast는 kind가 같으면) 같은 일정이다.
    goods·other는 kind가 같아도 제목이 서로 포함될 때만 같은 일정이다 (같은 날 마감인 서로 다른 굿즈를 지키려고).
    제목은 `match_title`(흔한 단어·연도를 뺀 정규화)로 비교한다. 정규화한 제목이 빈 문자열(기호뿐이거나 흔한 단어뿐)이면 '포함'은 따지지 않는다 — 빈 문자열은 모든 문자열에 들어 있기 때문."""
    if a["start"] != b["start"] or a.get("end") != b.get("end"):
        return False
    na, nb = match_title(a["title"]), match_title(b["title"])
    if na and nb and (na in nb or nb in na):
        return True
    return a["kind"] == b["kind"] and a["kind"] in config.EVENT_DEDUP_SAME_KIND  # goods·other는 kind만으로는 합치지 않는다


def find_duplicate(event: dict, stored: list[dict]) -> dict | None:
    """다른 공지(source가 다른)에서 먼저 저장된 같은 일정. 없으면 None."""
    for other in stored:
        if other.get("source") != event.get("source") and is_duplicate(event, other):
            return other
    return None


# ---------------------------------------------------------------- 상태
def empty_doc() -> dict:
    return {"updatedAt": None, "processed": {}, "items": []}


def notice_number(news_id: str) -> str | None:
    m = _NOTICE_ID.fullmatch(str(news_id))
    return m.group(1) if m else None


def select_targets(news_items: list[dict], processed: dict, today: date) -> list[dict]:
    """처리할 공지(오래된 공지 = 공지 번호 오름차순부터, 최대 EVENTS_PER_RUN). 이미 처리된 공지는 제외하되 error는 시도 횟수가 남아 있으면 포함한다."""
    picked = []
    for it in news_items:
        number = notice_number(it.get("id", ""))
        if number is None:
            continue
        try:
            day = timeutil.parse_kst(it["date"]).astimezone(config.KST).date()
        except (KeyError, ValueError, TypeError):
            continue
        if (today - day).days > config.EVENTS_WINDOW_DAYS:
            continue
        rec = processed.get(it["id"])
        if rec is not None:  # 이미 처리됨. error이고 시도 횟수가 남아 있을 때만 다시 대상이 된다
            retry = isinstance(rec, dict) and rec.get("result") == "error" and int(rec.get("tries") or 0) < config.EVENTS_MAX_TRIES
            if not retry:
                continue
        picked.append((day, int(number), it))
    picked.sort(key=lambda t: t[1])  # 공지 번호 오름차순 (= 오래된 공지부터)
    return [it for _, _, it in picked[: config.EVENTS_PER_RUN]]


def prune(doc: dict, today: date, now: datetime) -> tuple[int, int]:
    """보관 규칙 적용 (제자리) → (삭제한 일정 수, 삭제한 processed 수)."""
    keep = []
    for ev in doc["items"]:
        try:
            last = parse_when(ev.get("end") or ev["start"]).day
        except (KeyError, ValueError):
            log.warning("자동 일정을 읽을 수 없어 삭제: %s", ev.get("id"))
            continue
        if (today - last).days <= config.EVENTS_KEEP_AFTER_END_DAYS:
            keep.append(ev)
    removed_items = len(doc["items"]) - len(keep)
    doc["items"] = keep
    old = []
    for key, rec in doc["processed"].items():
        try:
            if now - timeutil.parse_kst(rec["at"]) > timedelta(days=config.EVENTS_PROCESSED_KEEP_DAYS):
                old.append(key)
        except (KeyError, ValueError, TypeError):
            old.append(key)
    for key in old:
        del doc["processed"][key]
    return removed_items, len(old)


@dataclass
class Report:
    targets: int = 0
    events: int = 0  # 일정이 하나 이상 저장 후보가 된 공지 수 (중복으로 전부 걸러져도 events)
    none: int = 0
    no_text: int = 0
    error: int = 0
    deferred: int = 0  # 일시 오류로 기록 없이 다음 실행에 미룬 공지 수
    new_items: int = 0
    duplicates: int = 0  # 다른 공지의 일정과 겹쳐 버린 수
    dropped: int = 0  # 검증에서 버린 후보 수
    pruned_items: int = 0
    api_calls: int = 0
    model: str | None = None
    abort: claude_events.ApiError | None = None  # API 오류로 멈췄다면 그 오류 (상태·error.type만 담김)

    def summary(self) -> str:
        text = (f"일정 추출: 대상 {self.targets}개 → events {self.events} · none {self.none} · no_text {self.no_text} · error {self.error}"
                f" · 보류 {self.deferred} | 새 일정 {self.new_items}개 (중복 제외 {self.duplicates}, 검증 탈락 {self.dropped}) · API 호출 {self.api_calls}회")
        if self.model:
            text += f" · 모델 {self.model}"
        if self.abort:
            text += f" · 중단({self.abort})"
        return text


@dataclass
class Result:
    doc: dict
    fresh: list  # 이번에 새로 저장된 일정 (알림 판정 입력)
    report: Report


def _record(doc: dict, news_id: str, result: str, now_iso: str, tries: int) -> None:
    doc["processed"][news_id] = {"at": now_iso, "result": result, "tries": tries}


def run(prev: dict, news_items: list[dict], *, members: dict, index: tagging.TagIndex, client: claude_events.Client, now: datetime, now_iso: str,
        get, sleep=time.sleep) -> Result:
    """이전 상태 + 병합된 news → 새 상태. 예상되는 오류(API·네트워크·형식)는 안에서 처리하므로 예외로 끝나지 않는다. prev는 바꾸지 않는다."""
    doc = {"updatedAt": prev.get("updatedAt"), "processed": copy.deepcopy(prev.get("processed") or {}), "items": copy.deepcopy(prev.get("items") or [])}
    today = now.astimezone(config.KST).date()
    rep = Report()
    rep.pruned_items, _ = prune(doc, today, now)
    targets = select_targets(news_items, doc["processed"], today)
    rep.targets = len(targets)
    fresh: list[dict] = []
    fetched = 0
    for it in targets:
        news_id = it["id"]
        number = notice_number(news_id)
        tries = int((doc["processed"].get(news_id) or {}).get("tries") or 0) + 1
        if fetched:
            sleep(config.REQUEST_DELAY)
        fetched += 1
        try:
            body = stellive_notice_detail.fetch_body(number, get=get)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 400 <= status < 500 and status not in (408, 429):
                log.warning("공지 %s 본문 읽기 실패: HTTP %s → error", news_id, status)
                _record(doc, news_id, "error", now_iso, tries)
                rep.error += 1
            else:
                log.warning("공지 %s 본문 읽기 실패: HTTP %s — 다음 실행에 다시 시도합니다", news_id, status)
                rep.deferred += 1
            continue
        except requests.RequestException as e:
            log.warning("공지 %s 본문 읽기 실패: %s — 다음 실행에 다시 시도합니다", news_id, type(e).__name__)
            rep.deferred += 1
            continue
        except stellive_notice_detail.BodyParseError as e:
            log.warning("공지 %s: %s → error", news_id, e)
            _record(doc, news_id, "error", now_iso, tries)
            rep.error += 1
            continue

        if stellive_notice_detail.char_count(body) < config.EVENTS_NO_TEXT_CHARS:
            log.info("공지 %s: 본문 %d자 — 이미지 위주 공지라 건너뜀 (no_text)", news_id, stellive_notice_detail.char_count(body))
            _record(doc, news_id, "no_text", now_iso, tries)
            rep.no_text += 1
            continue

        notice_day = timeutil.parse_kst(it["date"]).astimezone(config.KST).date()
        try:
            raw = claude_events.extract(client, title=it.get("title") or "", date=notice_day.isoformat(), body=body, members=members)
        except claude_events.ApiError as e:  # 키 거부·요청 거부·일시 오류: 기록 없이 멈춘다 (재시도 횟수를 쓰지 않는다)
            rep.abort = e
            rep.deferred += 1
            log.warning("Claude API 오류(%s) — 이 실행의 남은 공지는 처리하지 않고 다음 실행에 다시 시도합니다", e)
            break
        except claude_events.BadOutput:
            log.warning("공지 %s: 모델 출력을 읽지 못해 error (%d/%d회)", news_id, tries, config.EVENTS_MAX_TRIES)
            _record(doc, news_id, "error", now_iso, tries)
            rep.error += 1
            continue

        checked = validate_events(raw, notice_id=news_id, notice_title=it.get("title") or "", notice_day=notice_day, members=members, index=index)
        rep.dropped += checked.dropped
        if not checked.events:
            _record(doc, news_id, "none", now_iso, tries)
            rep.none += 1
            continue
        _record(doc, news_id, "events", now_iso, tries)
        rep.events += 1
        n = 0
        for ev in checked.events:
            candidate = {**ev, "source": news_id}
            other = find_duplicate(candidate, doc["items"])
            if other is not None:
                rep.duplicates += 1
                log.info("자동 일정 중복 — %s의 일정은 먼저 저장된 %s(%s)와 같아 저장하지 않습니다", news_id, other.get("id"), other.get("source"))
                continue
            n += 1
            item = {**candidate, "id": f"auto-{news_id}-{n}", "url": it.get("url") or config.NEWS_ITEM_URL.format(number=number)}
            item = {k: item[k] for k in _ITEM_FIELDS if k in item}
            doc["items"].append(item)
            fresh.append(item)
            rep.new_items += 1

    doc["items"].sort(key=lambda e: (e["start"], e["id"]))
    doc["processed"] = dict(sorted(doc["processed"].items()))
    rep.api_calls = client.calls
    rep.model = client.response_model
    return Result(doc=doc, fresh=fresh, report=rep)
