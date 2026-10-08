"""갱신 정체 감시 (SPEC v1.1 기능 0-e). 판정은 전부 순수 함수고, GitHub·사이트 호출은 get/post를 주입받아 테스트가 네트워크 없이 돈다.

무엇을 막으려는가: 2026-10-07 `workflow_dispatch` 실행 하나가 시작도 못 하고 `waiting`에 남아 concurrency 그룹 `pages`를 잡았고,
이후 실행은 줄줄이 취소돼 사이트가 약 22.5시간 갱신되지 않았다. 외부 cron의 호출 자체는 성공(204)이라 아무도 몰랐다.

규칙 (값은 config.WATCHDOG_*):
- 배포된 사이트 news.json의 updatedAt이 90분을 **넘게** 지났으면 정체.
- 정체면 update.yml 실행 중 queued/waiting/in_progress 상태로 30분을 **넘은** 것을 취소한다 (정상 실행은 몇 분, timeout은 15분).
- 경고는 같은 정체로 처음 한 번, 이후 6시간마다 한 번. 상태를 저장하는 곳이 없으므로(커밋·Secret·캐시 없음) 이전 점검 실행의
  "경고 발송" 단계가 success였는지를 GitHub API로 읽어 마지막 경고 시각으로 쓴다. 그 조회가 실패하면 경고를 보내는 쪽으로 기운다
  (조용히 지나가는 것보다 한 번 더 울리는 편이 낫다).
- 사이트를 읽지 못하면(판정 불가) 아무것도 취소하지 않는다. 근거 없이 실행을 취소하지 않는다.

**GITHUB_TOKEN은 비밀이다.** 헤더로만 보내고, 오류는 HTTP 상태·예외 종류만 기록한다(requests 예외 메시지에는 URL이 들어 있다).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests

from . import config, http

log = logging.getLogger(__name__)


class CheckError(RuntimeError):
    """점검 중 호출 실패. 메시지에는 HTTP 상태나 예외 종류만 담긴다 (토큰·URL·응답 본문 없음)."""


@dataclass(frozen=True)
class Run:
    id: int
    status: str
    started: datetime  # aware. run_started_at이 있으면 그것, 없으면 created_at
    url: str = ""


@dataclass
class Outcome:
    state: str  # "ok" | "stale" | "unknown"
    updated_at: datetime | None = None
    age: timedelta | None = None
    stuck: list = field(default_factory=list)  # [(Run, 결과 문구)] — 취소한(하려던) 실행
    runs_error: str | None = None
    alert: dict | None = None  # 보낼 웹훅 페이로드. 없으면 경고하지 않는다
    reason: str = ""  # 경고하지 않는 이유 / 상태 설명 (로그용)


# ================================ 판정 (순수) ===================================
def parse_time(value: str) -> datetime:
    """ISO 8601(끝이 'Z'여도 됨) → aware datetime. timezone이 없으면 ValueError."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timezone 정보가 없는 시각")
    return dt


def is_stale(updated_at: datetime, now: datetime) -> bool:
    return now - updated_at > timedelta(minutes=config.WATCHDOG_STALE_MINUTES)  # 정확히 90분은 아직 정상


def run_from_api(d: dict) -> Run:
    return Run(int(d["id"]), str(d["status"]), parse_time(d.get("run_started_at") or d["created_at"]), str(d.get("html_url") or ""))


def stuck_runs(runs: list[Run], now: datetime) -> list[Run]:
    """취소 대상: 상태가 queued/waiting/in_progress이고 시작한 지 30분을 넘은 것. 가장 오래된 것부터."""
    limit = timedelta(minutes=config.WATCHDOG_RUN_MAX_AGE_MINUTES)
    return sorted((r for r in runs if r.status in config.WATCHDOG_RUN_STATUSES and now - r.started > limit), key=lambda r: r.started)


def should_alert(updated_at: datetime, now: datetime, last_alert: datetime | None) -> bool:
    """정체가 시작된 뒤 처음 한 번, 이후 6시간마다 한 번.
    last_alert가 없거나 updatedAt보다 이전이면(= 이전 정체 때의 경고) 새 정체다. 점검이 몇 분 늦거나 빨라도 6시간째가 밀리지 않게 여유를 둔다."""
    if last_alert is None or last_alert < updated_at:
        return True
    return now - last_alert >= timedelta(hours=config.WATCHDOG_REPEAT_HOURS) - timedelta(minutes=config.WATCHDOG_REPEAT_GRACE_MINUTES)


def describe(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    return f"{minutes}분" if minutes < 120 else f"{minutes // 60}시간 {minutes % 60}분"


def build_alert(*, now: datetime, updated_at: datetime, stuck: list, runs_error: str | None, repo: str) -> dict:
    """디스코드 웹훅 페이로드 1개(임베드 1개). send_alerts.py가 읽는 알림 파일 형식과 같다."""
    last = updated_at.astimezone(config.KST).strftime("%Y-%m-%d %H:%M")
    lines = [f"마지막 갱신: {last} KST ({describe(now - updated_at)} 전)"]
    if stuck:
        lines.append(f"정체된 update 실행 {len(stuck)}개를 처리했어요:")
        for run, outcome in stuck[:5]:
            lines.append(f"• #{run.id} · {run.status} · {describe(now - run.started)} 경과 · {outcome}")
        if len(stuck) > 5:
            lines.append(f"• 외 {len(stuck) - 5}개")
    elif runs_error:
        lines.append(f"실행 목록을 읽지 못했어요 ({runs_error}) — Actions 화면에서 직접 확인하세요.")
    else:
        lines.append("정체된 실행은 없어요. 외부 cron(cron-job.org)이 update.yml을 부르는지, 토큰이 만료되지 않았는지 확인하세요.")
    lines.append(f"같은 정체의 다음 경고는 {config.WATCHDOG_REPEAT_HOURS}시간 뒤예요.")
    embed = {
        "author": {"name": "사이트 감시 · 갱신 정체"},
        "title": f"사이트 갱신이 {describe(now - updated_at)}째 멈췄어요",
        "description": "\n".join(lines)[:4000],
        "url": f"https://github.com/{repo}/actions/workflows/{config.UPDATE_WORKFLOW_FILE}",
        "color": config.WATCHDOG_COLOR,
        "timestamp": now.isoformat(timespec="seconds"),
    }
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


# ================================ 호출 =========================================
def fetch_updated_at(site_url: str, now: datetime, get=http.get) -> datetime:
    """배포된 사이트의 news.json updatedAt. 읽을 수 없으면 CheckError (판정 불가)."""
    url = f"{site_url}data/news.json?t={int(now.timestamp())}"  # 캐시 회피
    try:
        return parse_time(get(url).json()["updatedAt"])
    except requests.HTTPError as e:
        raise CheckError(f"사이트 news.json HTTP {e.response.status_code if e.response is not None else '?'}") from None
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        raise CheckError(f"사이트 news.json {type(e).__name__}") from None


class GitHub:
    """필요한 GitHub REST 호출만 모은 얇은 클라이언트. 토큰은 Authorization 헤더로만 간다."""

    def __init__(self, repo: str, token: str | None, *, get=http.get, post=http.post_json):
        self.repo, self._token, self._get, self._post = repo, token, get, post

    @property
    def can_write(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _api(self, path: str) -> str:
        return f"{config.GITHUB_API_URL}/repos/{self.repo}/{path}"

    def _json(self, path: str, params: dict | None = None) -> dict:
        url = self._api(path) + (f"?{urlencode(params)}" if params else "")
        try:
            return self._get(url, headers=self._headers()).json()
        except requests.HTTPError as e:
            raise CheckError(f"GitHub HTTP {e.response.status_code if e.response is not None else '?'}") from None
        except (requests.RequestException, ValueError) as e:  # 메시지에 URL이 들어 있을 수 있어 종류만 남긴다
            raise CheckError(f"GitHub {type(e).__name__}") from None

    def workflow_runs(self, workflow: str, *, status: str | None = None, per_page: int = 50) -> list[dict]:
        params = {"per_page": per_page, **({"status": status} if status else {})}
        return list(self._json(f"actions/workflows/{workflow}/runs", params).get("workflow_runs") or [])

    def update_runs(self) -> list[Run]:
        """update.yml의 queued/waiting/in_progress 실행 (상태별로 한 번씩 조회, 중복 제거)."""
        seen: dict[int, Run] = {}
        for status in config.WATCHDOG_RUN_STATUSES:
            for d in self.workflow_runs(config.UPDATE_WORKFLOW_FILE, status=status):
                run = run_from_api(d)
                seen.setdefault(run.id, run)
        return list(seen.values())

    def jobs(self, run_id: int) -> list[dict]:
        return list(self._json(f"actions/runs/{run_id}/jobs", {"per_page": 10}).get("jobs") or [])

    def cancel(self, run_id: int) -> str:
        """실행 취소. 일반 취소가 거부되면(409) 강제 취소를 한 번 더 시도한다. 결과 문구를 돌려주고, 둘 다 실패하면 CheckError."""
        for suffix, done in (("cancel", "취소 요청함"), ("force-cancel", "강제 취소 요청함")):
            try:
                self._post(self._api(f"actions/runs/{run_id}/{suffix}"), None, headers=self._headers())
                return done
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if suffix == "cancel" and status == 409:
                    continue
                raise CheckError(f"취소 실패 HTTP {status}") from None
            except requests.RequestException as e:
                raise CheckError(f"취소 실패 {type(e).__name__}") from None
        raise CheckError("취소 실패")  # 도달하지 않는다 (force-cancel이 성공하거나 예외를 던진다)


def last_alert_time(gh: GitHub, now: datetime, *, current_run_id: str | int | None = None) -> datetime | None:
    """이전 점검 실행 중 "경고 발송" 단계가 success였던 가장 최근 실행의 시작 시각. 없으면 None. 조회 실패는 CheckError."""
    lookback = now - timedelta(hours=config.WATCHDOG_REPEAT_HOURS + 1)  # 6시간 간격 판정에 필요한 만큼에 1시간 여유
    best = None
    for d in gh.workflow_runs(config.WATCHDOG_WORKFLOW_FILE, status="completed", per_page=config.WATCHDOG_RUNS_PER_PAGE):
        if current_run_id is not None and str(d.get("id")) == str(current_run_id):
            continue
        run = run_from_api(d)
        if run.started < lookback or (best is not None and run.started <= best):
            continue
        sent = any(step.get("name") == config.WATCHDOG_ALERT_STEP and step.get("conclusion") == "success"
                   for job in gh.jobs(run.id) for step in job.get("steps") or [])
        if sent:
            best = run.started
    return best


# ================================ 점검 =========================================
def check(*, now: datetime, gh: GitHub, site_url: str, repo: str, get=http.get, current_run_id=None, dry_run: bool = False) -> Outcome:
    """점검 1회. 정체면 오래된 update 실행을 취소하고(dry_run이면 하려는 것만 기록) 경고를 보낼지 판정한다."""
    try:
        updated_at = fetch_updated_at(site_url, now, get)
    except CheckError as e:
        return Outcome("unknown", reason=f"판정 불가 — {e}. 아무것도 취소하지 않습니다")
    age = now - updated_at
    if not is_stale(updated_at, now):
        return Outcome("ok", updated_at, age, reason=f"정상: 마지막 갱신 {describe(age)} 전")

    out = Outcome("stale", updated_at, age)
    try:
        stuck = stuck_runs(gh.update_runs(), now)
    except CheckError as e:
        stuck, out.runs_error = [], str(e)
    for run in stuck:
        if dry_run:
            out.stuck.append((run, "취소 예정 (dry-run)"))
        elif not gh.can_write:
            out.stuck.append((run, "취소 못 함 (GITHUB_TOKEN 없음)"))
        else:
            try:
                out.stuck.append((run, gh.cancel(run.id)))
            except CheckError as e:
                out.stuck.append((run, str(e)))
    try:
        last = last_alert_time(gh, now, current_run_id=current_run_id)
    except CheckError as e:
        log.warning("이전 경고 시각을 읽지 못해 경고를 보내는 쪽으로 판단합니다 (%s)", e)
        last = None
    if should_alert(updated_at, now, last):
        out.alert = build_alert(now=now, updated_at=updated_at, stuck=out.stuck, runs_error=out.runs_error, repo=repo)
        out.reason = f"정체: 마지막 갱신 {describe(age)} 전 — 경고를 보냅니다"
    else:
        out.reason = f"정체: 마지막 갱신 {describe(age)} 전 — 같은 정체의 경고가 {describe(now - last)} 전에 나가서 이번에는 보내지 않습니다"
    return out
