"""[일회성 도구] 대표곡 10곡의 유튜브 영상 후보를 찾아 표로 보여준다 (SPEC v1.1 기능 1).

- 후보만 보여준다. **songs.json을 쓰는 코드는 이 파일에 없다.** 사용자가 고른 videoId를 사람(또는 Claude가 Edit으로)이 `yt`에 넣는다.
- 1차: 곡의 멤버별 유튜브 채널 안에서 곡 제목으로 검색(`search.list`, 호출당 100유닛). 채널 키가 없는 협업자(예: 도깨비꽃의 TAK)는 건너뛴다.
- 2차: 1차에서 후보가 하나도 없는 곡만 채널 제한 없이 `멤버 이름 + 곡명`으로 검색.
- `search.list`는 업데이터에서 코드로 막혀 있다(`config.YOUTUBE_API_ENDPOINTS`). 이 도구가 그 예외이며, 그래서 `tools/`는 업데이터가 import하지 않는다.
- 키는 `.env`의 YOUTUBE_API_KEY → `X-Goog-Api-Key` 헤더로만 보낸다. 오류는 HTTP 상태와 reason만 출력한다(예외 메시지·응답 본문 금지).

사용:
    python tools/find_song_videos.py --plan                 # 네트워크 없이 대상·쿼리·예상 유닛만 출력
    python tools/find_song_videos.py                        # 실호출 (1차 11호출 = 1,100유닛, 최악 2차까지 21호출 = 2,100유닛)
    python tools/find_song_videos.py --only 눈꽃,불꽃        # 일부 곡만 다시
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # `python tools/find_song_videos.py`로 실행하면 sys.path[0]이 tools/라서 updater를 못 찾는다
    sys.path.insert(0, str(ROOT))

from updater import config, http, redact, timeutil  # noqa: E402

log = logging.getLogger("find_song_videos")

TARGET_TITLES = (
    "SYNC 100%", "불꽃", "슈퍼삐질게하는법", "Ready to Fire!", "DIVE 2 FIGHT",
    "Colorful Tempo", "꿈의 신호", "도깨비꽃", "Lulala! Lululala!", "눈꽃",
)
SEARCH_UNITS = 100  # search.list 호출당 할당량
RESULTS_PER_QUERY = 3
DEFAULT_MAX_CALLS = 21  # 1차 11 + 2차 최대 10. 이보다 많이는 부르지 않는다
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


class SearchError(RuntimeError):
    """검색 실패. 메시지에는 HTTP 상태·reason 또는 예외 종류만 담는다 (키·URL·응답 본문 없음)."""


class Abort(SearchError):
    """할당량 초과·키 거부: 더 부르지 않고 지금까지의 결과만 보여준다."""


@dataclass
class Target:
    title: str
    who: list
    members: list  # [(멤버 key, 이름, 채널 ID)] — 채널이 있는 멤버만


@dataclass
class Query:
    song: str
    kind: str  # "channel" | "global"
    q: str
    channel_id: str | None
    label: str  # 사람이 읽는 라벨(멤버 이름 또는 '전체 검색')


@dataclass
class Candidate:
    video_id: str
    title: str
    channel: str
    published: str  # YYYY-MM-DD (KST)
    channel_id: str = ""

    @property
    def url(self) -> str:
        return WATCH_URL.format(video_id=self.video_id)


@dataclass
class SongResult:
    title: str
    found: list = field(default_factory=list)  # [(Query, [Candidate])]
    errors: list = field(default_factory=list)  # ["라벨: HTTP 500 -"]


# ---------------------------------------------------------------- 계획
def find_targets(songs_doc: dict, members_doc: dict, titles) -> tuple[list[Target], list[str]]:
    """songs.json에서 대상 곡을 찾는다. 없거나, 제목이 겹치거나, 이미 yt가 있으면 경고하고 뺀다."""
    members = members_doc.get("members", {})
    targets, warnings = [], []
    for title in titles:
        rows = [s for s in songs_doc.get("items", []) if s.get("title") == title]
        if not rows:
            warnings.append(f"{title}: songs.json에 없음 — 건너뜀")
            continue
        if len(rows) > 1:
            warnings.append(f"{title}: songs.json에 {len(rows)}개 — 어느 곡인지 알 수 없어 건너뜀")
            continue
        row = rows[0]
        if row.get("yt"):
            warnings.append(f"{title}: 이미 yt={row['yt']} — 건너뜀")
            continue
        who = list(row.get("who") or [])
        chans = [(k, members[k].get("n", k), members[k]["yt_id"]) for k in who if k in members and members[k].get("yt_id")]
        if not chans:
            warnings.append(f"{title}: who={who}에 채널이 있는 멤버가 없음 — 전체 검색만 시도")
        targets.append(Target(title, who, chans))
    return targets, warnings


def first_pass(targets: list[Target]) -> list[Query]:
    return [Query(t.title, "channel", t.title, cid, name) for t in targets for _, name, cid in t.members]


def global_query(target: Target, members_doc: dict) -> Query:
    members = members_doc.get("members", {})
    name = next((members[k]["n"] for k in target.who if k in members), "")
    return Query(target.title, "global", f"{name} {target.title}".strip(), None, "전체 검색")


def plan_text(targets: list[Target], warnings: list[str], max_calls: int) -> str:
    queries = first_pass(targets)
    no_channel = [t for t in targets if not t.members]
    worst = len(queries) + len(targets)  # 2차는 곡마다 최대 1회
    lines = [f"대상 {len(targets)}곡"]
    for w in warnings:
        lines.append(f"  경고: {w}")
    for t in targets:
        if t.members:
            for _, name, cid in t.members:
                lines.append(f"  1차  {t.title!r:24} 채널={name} ({cid})")
        else:
            lines.append(f"  1차  {t.title!r:24} 채널 없음")
        lines.append(f"  2차  {t.title!r:24} 1차 후보가 없을 때만: '<멤버 이름> {t.title}'")
    lines.append(f"1차 호출 {len(queries)}회 = {len(queries) * SEARCH_UNITS:,}유닛")
    lines.append(f"최악(2차까지) {worst}회 = {worst * SEARCH_UNITS:,}유닛 (일일 10,000 중), 호출 상한 {max_calls}회")
    if no_channel:
        lines.append(f"  채널 없는 곡 {len(no_channel)}곡은 1차 없이 2차로 바로 간다")
    return "\n".join(lines)


# ---------------------------------------------------------------- 호출
def _reason(response) -> str | None:
    try:
        return response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def search(query: Query, api_key: str, get=http.get) -> list[Candidate]:
    params = {"part": "snippet", "type": "video", "maxResults": RESULTS_PER_QUERY, "q": query.q}
    if query.channel_id:
        params["channelId"] = query.channel_id
    url = f"{config.YOUTUBE_API_URL}/search?{urlencode(params)}"  # 키는 URL에 넣지 않는다
    try:
        data = get(url, headers={config.YOUTUBE_API_KEY_HEADER: api_key}).json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        reason = _reason(e.response)
        detail = f"HTTP {status} {reason or '-'}"
        if status in (400, 401) or (status == 403 and reason not in _QUOTA_REASONS and reason != "rateLimitExceeded"):
            raise Abort(f"키 거부 가능성 — {detail}") from None
        if status == 403 and reason in _QUOTA_REASONS:
            raise Abort(f"할당량 초과 — {detail}") from None
        raise SearchError(detail) from None
    except (requests.RequestException, ValueError) as e:  # 메시지에 URL이 들어 있을 수 있어 종류만 남긴다
        raise SearchError(type(e).__name__) from None
    out = []
    for item in data.get("items") or []:
        snip = item.get("snippet") or {}
        vid = (item.get("id") or {}).get("videoId")
        if not vid:
            continue
        try:
            published = timeutil.to_kst_iso(snip["publishedAt"])[:10]
        except (KeyError, ValueError):
            published = "-"
        out.append(Candidate(vid, html.unescape(snip.get("title") or ""), html.unescape(snip.get("channelTitle") or ""), published, snip.get("channelId") or ""))
    return out


def run(targets: list[Target], members_doc: dict, api_key: str, *, get=http.get, sleep=time.sleep, max_calls: int = DEFAULT_MAX_CALLS) -> tuple[list[SongResult], int, str | None]:
    """(곡별 결과, 실제 호출 수, 중단 사유). 호출 수가 max_calls에 닿거나 Abort가 나면 거기서 멈춘다."""
    calls = 0
    results = [SongResult(t.title) for t in targets]
    by_title = {r.title: r for r in results}
    stopped = None

    def call(q: Query):
        nonlocal calls
        if calls >= max_calls:
            raise Abort(f"호출 상한 {max_calls}회에 도달")
        if calls:
            sleep(config.REQUEST_DELAY)
        calls += 1
        res = by_title[q.song]
        try:
            res.found.append((q, search(q, api_key, get)))
        except Abort:
            raise
        except SearchError as e:
            res.errors.append(f"{q.label}: {e}")

    try:
        for q in first_pass(targets):
            call(q)
        for t in targets:
            res = by_title[t.title]
            if not any(cands for _, cands in res.found) and not res.errors:
                call(global_query(t, members_doc))
    except Abort as e:
        stopped = str(e)
    return results, calls, stopped


def channel_kind(channel_id: str, members_doc: dict | None, who: list) -> str:
    """후보 채널이 공식인지: 곡의 멤버 본인 / 스텔라이브 공식 / 다른 멤버 / 그 밖(외부). 사람이 고르는 데 쓰는 표시일 뿐이다."""
    if not channel_id or not members_doc:
        return "채널 구분 불가"
    if channel_id == (members_doc.get("official") or {}).get("yt_id"):
        return "✔ 스텔라이브 공식 채널"
    for key, m in members_doc.get("members", {}).items():
        if m.get("yt_id") == channel_id:
            return f"✔ 멤버 본인 채널({m.get('n', key)})" if key in who else f"△ 다른 멤버 채널({m.get('n', key)})"
    return "✘ 외부 채널(공식 아님)"


def results_text(results: list[SongResult], calls: int, stopped: str | None, members_doc: dict | None = None, whos: dict | None = None) -> str:
    lines = []
    for r in results:
        lines.append(f"\n## {r.title}")
        seen = set()
        n = 0
        for q, cands in r.found:
            for c in cands:
                if c.video_id in seen:
                    continue
                seen.add(c.video_id)
                n += 1
                kind = channel_kind(c.channel_id, members_doc, (whos or {}).get(r.title, []))
                lines.append(f"  {n}. [{q.label}] {c.title}\n     채널: {c.channel} — {kind}\n     게시일: {c.published} · ID: {c.video_id}\n     {c.url}")
        if not n:
            lines.append("  (후보 없음)")
        for e in r.errors:
            lines.append(f"  오류: {e}")
    lines.append(f"\nAPI 호출 {calls}회 = {calls * SEARCH_UNITS:,}유닛")
    if stopped:
        lines.append(f"중단: {stopped}")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI
def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None, *, get=http.get, sleep=time.sleep, environ=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", action="store_true", help="네트워크 없이 대상·쿼리·예상 유닛만 출력")
    ap.add_argument("--only", help="쉼표로 구분한 곡 제목만 (다시 찾을 때)")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help=f"search.list 호출 상한 (기본 {DEFAULT_MAX_CALLS})")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글이 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    redact.configure_logging()

    titles = TARGET_TITLES
    if args.only:
        wanted = [t.strip() for t in args.only.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in TARGET_TITLES]
        if unknown:
            print(f"대상 10곡이 아닌 제목: {unknown}", file=sys.stderr)
            return 2
        titles = tuple(wanted)
    songs_doc, members_doc = _read_json(config.DATA_DIR / "songs.json"), _read_json(config.DATA_DIR / "members.json")
    targets, warnings = find_targets(songs_doc, members_doc, titles)
    print(plan_text(targets, warnings, args.max_calls))
    if len(first_pass(targets)) > args.max_calls:
        print(f"1차 호출이 상한 {args.max_calls}회를 넘는다 — 중단", file=sys.stderr)
        return 2
    if args.plan or not targets:
        return 0

    if environ is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        environ = os.environ
    api_key = (environ.get(config.YOUTUBE_API_KEY_ENV) or "").strip()
    if not api_key:
        print(f"{config.YOUTUBE_API_KEY_ENV}가 없다 (.env 확인) — 중단", file=sys.stderr)
        return 2
    redact.register(api_key)

    results, calls, stopped = run(targets, members_doc, api_key, get=get, sleep=sleep, max_calls=args.max_calls)
    print(results_text(results, calls, stopped, members_doc, {t.title: t.who for t in targets}))
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
