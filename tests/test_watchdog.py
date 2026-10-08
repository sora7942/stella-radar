"""갱신 정체 감시(기능 0-e): updater/watchdog.py의 판정과 watchdog.py 스크립트. 사이트·GitHub는 전부 가짜 get/post — 네트워크 없음.
핵심 약속: ① 정상이면 아무것도 하지 않는다 ② 근거(판정 가능한 정체) 없이는 실행을 취소하지 않는다 ③ 경고는 정체당 처음 한 번 + 6시간마다 한 번
④ GITHUB_TOKEN은 헤더로만 가고 로그·출력·알림 파일 어디에도 남지 않는다 ⑤ 디스코드 웹훅은 이 코드가 읽지 않는다."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests

import send_alerts
import watchdog as script
from conftest import ROOT, make_response
from updater import config, http, watchdog as wd

KST = config.KST
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=KST)
TOKEN = "TESTTOKEN-not-a-real-token-0123456789"  # 'ghp_'·'github_pat_' 모양이 아니어야 저장소 스캔 테스트와 부딪히지 않는다
REPO = "sora7942/stella-radar"
SITE = "https://sora7942.github.io/stella-radar/"


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_dict(rid, status, started, **extra):
    return {"id": rid, "status": status, "created_at": z(started), "run_started_at": z(started), "html_url": f"https://github.com/{REPO}/actions/runs/{rid}", **extra}


def http_error(status):
    """실제 requests 오류처럼 메시지에 (토큰이 든) URL을 넣는다 — 우리 코드가 이 메시지를 쓰지 않는지 시험하려는 것."""
    return requests.HTTPError(f"{status} Error for url: https://api.github.com/x?access_token={TOKEN}", response=make_response(status, b"{}"))


class World:
    """가짜 사이트 + 가짜 GitHub. calls는 (메서드, URL, 헤더)를 기록한다.
    fail[(메서드, URL 일부)] = 상태 코드(int) 또는 예외 — 그 요청이 실패한다."""

    def __init__(self, *, updated_at=ago(minutes=40), update_runs=(), watchdog_runs=(), jobs=None, site_body=None, fail=None):
        self.updated_at, self.update_runs, self.watchdog_runs, self.jobs = updated_at, list(update_runs), list(watchdog_runs), jobs or {}
        self.site_body, self.fail = site_body, fail or {}
        self.calls: list[tuple[str, str, dict]] = []
        self.cancelled: list[str] = []

    def _maybe_fail(self, method, url):
        for (m, part), err in self.fail.items():
            if m == method and part in url:
                raise err if isinstance(err, Exception) else http_error(err)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw.get("headers") or {}))
        self._maybe_fail("GET", url)
        u = urlparse(url)
        if u.netloc == "sora7942.github.io":
            assert u.path.endswith("/data/news.json")
            body = self.site_body if self.site_body is not None else {"updatedAt": self.updated_at.isoformat(timespec="seconds")}
            return make_response(200, json.dumps(body))
        assert u.netloc == "api.github.com", url
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.endswith("/workflows/update.yml/runs"):
            return make_response(200, json.dumps({"workflow_runs": [r for r in self.update_runs if r["status"] == q["status"]]}))
        if u.path.endswith("/workflows/watchdog.yml/runs"):
            assert q["status"] == "completed"
            return make_response(200, json.dumps({"workflow_runs": self.watchdog_runs}))
        if u.path.endswith("/jobs"):
            rid = int(u.path.split("/")[-2])
            return make_response(200, json.dumps({"jobs": [{"steps": self.jobs.get(rid, [])}]}))
        raise AssertionError(f"예상 밖의 GET: {url}")

    def post(self, url, payload=None, **kw):
        self.calls.append(("POST", url, kw.get("headers") or {}))
        self._maybe_fail("POST", url)
        assert payload is None and urlparse(url).netloc == "api.github.com"
        self.cancelled.append(urlparse(url).path)
        return make_response(202, b"{}")

    @property
    def github_calls(self):
        return [c for c in self.calls if "api.github.com" in c[1]]

    @property
    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def alert_run(rid, started, *, sent):
    """이전 점검 실행 + 그 실행의 단계 목록. sent면 '경고 발송'이 success, 아니면 skipped."""
    steps = [{"name": "점검", "conclusion": "success"}, {"name": config.WATCHDOG_ALERT_STEP, "conclusion": "success" if sent else "skipped"}]
    return run_dict(rid, "completed", started), steps


def make_world(prev=(), **kw):
    runs, jobs = [], {}
    for run, steps in prev:
        runs.append(run)
        jobs[run["id"]] = steps
    return World(watchdog_runs=runs, jobs=jobs, **kw)


def do_check(world, *, token=TOKEN, dry_run=False, current_run_id=None):
    gh = wd.GitHub(REPO, token, get=world.get, post=world.post)
    return wd.check(now=NOW, gh=gh, site_url=SITE, repo=REPO, get=world.get, current_run_id=current_run_id, dry_run=dry_run)


# ============================ 판정 (순수 함수) ================================
def test_stale_means_more_than_ninety_minutes():
    assert config.WATCHDOG_STALE_MINUTES == 90
    assert not wd.is_stale(ago(minutes=90), NOW)  # 정확히 90분은 아직 정상
    assert wd.is_stale(ago(minutes=90, seconds=1), NOW)
    assert not wd.is_stale(NOW + timedelta(minutes=5), NOW)  # 시계가 어긋나 미래여도 정체가 아니다


def test_run_age_threshold_is_strictly_more_than_thirty_minutes():
    runs = [wd.run_from_api(run_dict(i, "waiting", ago(minutes=m))) for i, m in ((1, 30), (2, 31), (3, 29))]
    assert [r.id for r in wd.stuck_runs(runs, NOW)] == [2]


def test_only_queued_waiting_in_progress_are_candidates_and_oldest_first():
    runs = [wd.run_from_api(run_dict(i, s, ago(hours=h))) for i, s, h in
            ((1, "in_progress", 1), (2, "waiting", 3), (3, "queued", 2), (4, "pending", 5), (5, "completed", 6), (6, "requested", 7))]
    assert [r.id for r in wd.stuck_runs(runs, NOW)] == [2, 3, 1]  # pending·completed·requested는 대상이 아니다


def test_run_start_time_prefers_run_started_at_and_falls_back_to_created_at():
    d = run_dict(1, "waiting", ago(hours=2))
    assert wd.run_from_api(d).started == ago(hours=2)
    d2 = {"id": 2, "status": "waiting", "created_at": z(ago(hours=1)), "run_started_at": None}
    assert wd.run_from_api(d2).started == ago(hours=1)
    assert wd.run_from_api(run_dict(3, "waiting", ago(minutes=5), run_started_at=z(ago(minutes=1)))).started == ago(minutes=1)  # 재실행은 새 시작 시각


@pytest.mark.parametrize("last, expect", [
    (None, True),                                   # 경고한 적 없음 → 정체가 시작된 뒤 처음
    (ago(hours=12), True),                          # 6시간이 훨씬 지남
    (ago(hours=6), True),
    (ago(hours=5, minutes=50), True),               # 점검이 조금 일찍 와도 6시간째를 건너뛰지 않는다 (여유 10분)
    (ago(hours=5, minutes=49, seconds=59), False),
    (ago(hours=1), False),                          # 방금 경고했다
    (ago(minutes=1), False),
])
def test_alert_repeats_every_six_hours(last, expect):
    updated = ago(hours=30)  # 정체가 아주 오래전에 시작됨. 마지막 경고는 그 뒤
    assert wd.should_alert(updated, NOW, last) is expect


def test_an_alert_from_before_the_last_update_belongs_to_an_earlier_stall():
    updated = ago(minutes=100)
    assert wd.should_alert(updated, NOW, ago(minutes=130)) is True   # 그 뒤 사이트가 복구됐다가 다시 멈췄다 → 새 정체
    assert wd.should_alert(updated, NOW, ago(minutes=95)) is False   # 이번 정체의 경고


def test_describe_uses_minutes_then_hours():
    assert wd.describe(timedelta(minutes=95)) == "95분" and wd.describe(timedelta(minutes=135)) == "2시간 15분" and wd.describe(timedelta(seconds=-5)) == "0분"


# ============================ 경고 메시지 =====================================
def stuck_pair(rid=7, minutes=61, status="waiting", outcome="취소 요청함"):
    return wd.run_from_api(run_dict(rid, status, ago(minutes=minutes))), outcome


def test_alert_payload_is_accepted_by_send_alerts_and_has_the_fields_the_dry_run_needs(tmp_path):
    payload = wd.build_alert(now=NOW, updated_at=ago(hours=22), stuck=[stuck_pair()], runs_error=None, repo=REPO)
    path = tmp_path / "alerts.json"
    path.write_text(json.dumps({"createdAt": NOW.isoformat(), "alertCount": 1, "messages": [payload]}, ensure_ascii=False), encoding="utf-8")
    assert send_alerts.load_messages(path) == [payload]  # 보내기 직전 검증을 통과한다
    (embed,) = payload["embeds"]
    assert embed["author"]["name"] and embed["title"] and isinstance(embed["color"], int) and embed["url"].endswith("/actions/workflows/update.yml")
    assert payload["allowed_mentions"] == {"parse": []}
    assert "22시간" in embed["title"]


def test_alert_lists_what_was_cancelled_and_when_the_site_last_updated():
    payload = wd.build_alert(now=NOW, updated_at=ago(hours=22), stuck=[stuck_pair(7, 61), stuck_pair(8, 40, "queued", "강제 취소 요청함")], runs_error=None, repo=REPO)
    text = payload["embeds"][0]["description"]
    assert "2026-10-07 14:00 KST" in text and "#7 · waiting · 61분 경과 · 취소 요청함" in text and "#8 · queued · 40분 경과 · 강제 취소 요청함" in text
    assert "6시간 뒤" in text


def test_alert_without_stuck_runs_points_at_the_external_cron():
    text = wd.build_alert(now=NOW, updated_at=ago(hours=3), stuck=[], runs_error=None, repo=REPO)["embeds"][0]["description"]
    assert "정체된 실행은 없어요" in text and "cron-job.org" in text and "토큰" in text


def test_alert_says_so_when_the_run_list_could_not_be_read():
    text = wd.build_alert(now=NOW, updated_at=ago(hours=3), stuck=[], runs_error="GitHub HTTP 500", repo=REPO)["embeds"][0]["description"]
    assert "읽지 못했어요 (GitHub HTTP 500)" in text and "cron-job.org" not in text


def test_alert_caps_the_run_list():
    stuck = [stuck_pair(i, 40 + i) for i in range(9)]
    text = wd.build_alert(now=NOW, updated_at=ago(hours=3), stuck=stuck, runs_error=None, repo=REPO)["embeds"][0]["description"]
    assert text.count("• #") == 5 and "외 4개" in text and len(text) < 4000


# ============================ 점검: 정상 ======================================
def test_healthy_site_does_nothing_at_all():
    world = make_world(updated_at=ago(minutes=40))
    out = do_check(world)
    assert out.state == "ok" and out.alert is None and out.stuck == []
    assert world.github_calls == [] and world.posts == []  # GitHub API를 부르지도 않는다 — 사이트 확인 1회뿐
    assert len(world.calls) == 1 and "/data/news.json?t=" in world.calls[0][1]


def test_exactly_ninety_minutes_is_still_healthy():
    assert do_check(make_world(updated_at=ago(minutes=90))).state == "ok"


# ============================ 점검: 정체 → 취소 + 경고 ==========================
def test_stale_site_cancels_the_old_waiting_run_and_alerts_once():
    stuck = run_dict(111, "waiting", ago(minutes=61))
    world = make_world(updated_at=ago(hours=22), update_runs=[stuck])
    out = do_check(world)
    assert out.state == "stale" and world.cancelled == [f"/repos/{REPO}/actions/runs/111/cancel"]
    assert [(r.id, res) for r, res in out.stuck] == [(111, "취소 요청함")]
    assert out.alert is not None and "#111" in out.alert["embeds"][0]["description"]


def test_fresh_runs_are_never_cancelled_even_when_the_site_is_stale():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(1, "in_progress", ago(minutes=5)), run_dict(2, "queued", ago(minutes=30))])
    out = do_check(world)
    assert world.posts == [] and out.stuck == [] and out.alert is not None  # 정상 실행이 돌고 있을 수 있다. 경고는 나간다 (정체는 사실이므로)


def test_an_in_progress_run_older_than_thirty_minutes_is_cancelled():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(5, "in_progress", ago(minutes=31))])
    do_check(world)
    assert world.cancelled == [f"/repos/{REPO}/actions/runs/5/cancel"]


def test_only_update_runs_are_looked_up_and_each_status_once():
    world = make_world(updated_at=ago(hours=3))
    do_check(world)
    listed = [c[1] for c in world.github_calls if "/workflows/update.yml/runs" in c[1]]
    assert sorted(parse_qs(urlparse(u).query)["status"][0] for u in listed) == ["in_progress", "queued", "waiting"]
    assert not any("pages" in c[1] for c in world.github_calls)


def test_run_appearing_under_two_statuses_is_cancelled_once():
    r = run_dict(9, "waiting", ago(minutes=50))
    world = make_world(updated_at=ago(hours=3), update_runs=[r, dict(r, status="queued")])  # 조회 사이에 상태가 바뀐 경우
    do_check(world)
    assert len(world.cancelled) == 1


def test_a_refused_cancel_falls_back_to_force_cancel():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(3, "waiting", ago(minutes=61))], fail={("POST", "/runs/3/cancel"): 409})
    out = do_check(world)
    assert world.cancelled == [f"/repos/{REPO}/actions/runs/3/force-cancel"] and out.stuck[0][1] == "강제 취소 요청함"


def test_a_failed_cancel_is_reported_not_raised_and_never_leaks_the_token():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(3, "waiting", ago(minutes=61)), run_dict(4, "waiting", ago(minutes=62))],
                       fail={("POST", "/runs/3/cancel"): 500})
    out = do_check(world)
    results = {r.id: res for r, res in out.stuck}
    assert results[3] == "취소 실패 HTTP 500" and results[4] == "취소 요청함"  # 하나가 실패해도 다음 실행은 취소한다
    assert TOKEN not in json.dumps(out.alert, ensure_ascii=False)


def test_connection_error_during_cancel_is_recorded_by_type_only():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(3, "waiting", ago(minutes=61))],
                       fail={("POST", "/runs/3/cancel"): requests.ConnectionError(f"boom {TOKEN}")})
    out = do_check(world)
    assert out.stuck[0][1] == "취소 실패 ConnectionError" and TOKEN not in str(out.stuck)


def test_run_list_failure_still_alerts_and_says_it_could_not_read():
    world = make_world(updated_at=ago(hours=3), fail={("GET", "/workflows/update.yml/runs"): 502})
    out = do_check(world)
    assert out.runs_error == "GitHub HTTP 502" and world.posts == [] and out.alert is not None
    assert "읽지 못했어요" in out.alert["embeds"][0]["description"] and TOKEN not in out.alert["embeds"][0]["description"]


def test_connection_error_listing_runs_is_recorded_by_type_only():
    world = make_world(updated_at=ago(hours=3), fail={("GET", "/workflows/update.yml/runs"): requests.ConnectionError(f"boom {TOKEN}")})
    out = do_check(world)
    assert out.runs_error == "GitHub ConnectionError" and TOKEN not in json.dumps(out.alert, ensure_ascii=False)


def test_no_token_means_no_cancel_but_still_an_alert():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(3, "waiting", ago(minutes=61))])
    out = do_check(world, token=None)
    assert world.posts == [] and "GITHUB_TOKEN 없음" in out.stuck[0][1] and out.alert is not None
    assert all("Authorization" not in h for _, _, h in world.github_calls)


def test_dry_run_never_posts():
    world = make_world(updated_at=ago(hours=3), update_runs=[run_dict(3, "waiting", ago(minutes=61))])
    out = do_check(world, dry_run=True)
    assert world.posts == [] and out.stuck[0][1].startswith("취소 예정")


# ============================ 점검: 판정 불가 ==================================
@pytest.mark.parametrize("kw", [
    {"fail": {("GET", "/data/news.json"): 404}},
    {"fail": {("GET", "/data/news.json"): 503}},
    {"fail": {("GET", "/data/news.json"): requests.ConnectionError(f"boom {TOKEN}")}},
    {"site_body": {"items": []}},                         # updatedAt 없음
    {"site_body": {"updatedAt": "2026-10-08T10:00:00"}},  # timezone 없음
    {"site_body": {"updatedAt": "어제"}},
])
def test_unreadable_site_cancels_nothing_and_stays_silent(kw):
    world = make_world(update_runs=[run_dict(3, "waiting", ago(hours=30))], **kw)
    out = do_check(world)
    assert out.state == "unknown" and out.alert is None and out.stuck == []
    assert world.posts == [] and world.github_calls == []  # 근거가 없으면 GitHub도 건드리지 않는다
    assert TOKEN not in out.reason and "판정 불가" in out.reason


# ============================ 경고 중복 억제 (정체당 한 번 + 6시간마다) ============
def stale_world(prev, **kw):
    return make_world(prev=prev, updated_at=ago(hours=30), update_runs=[run_dict(3, "waiting", ago(hours=29))], **kw)


def test_first_alert_of_a_stall_goes_out():
    out = do_check(stale_world([]))
    assert out.alert is not None


def test_no_repeat_within_six_hours_but_the_stuck_run_is_still_cancelled():
    world = stale_world([alert_run(50, ago(hours=1), sent=True)])
    out = do_check(world)
    assert out.alert is None and "60분 전에 나가서" in out.reason
    assert world.cancelled  # 경고만 억제한다. 정체된 실행은 계속 취소한다


def test_repeats_after_six_hours():
    assert do_check(stale_world([alert_run(50, ago(hours=6, minutes=5), sent=True)])).alert is not None


def test_checks_that_did_not_alert_do_not_count_as_alerts():
    prev = [alert_run(50, ago(hours=1), sent=False), alert_run(49, ago(hours=2), sent=False)]
    assert do_check(stale_world(prev)).alert is not None


def test_the_latest_alert_among_several_counts():
    prev = [alert_run(52, ago(hours=1), sent=False), alert_run(51, ago(hours=2), sent=True), alert_run(50, ago(hours=8), sent=True)]
    assert do_check(stale_world(prev)).alert is None


def test_an_alert_from_before_the_last_successful_update_does_not_suppress_a_new_stall():
    world = make_world(prev=[alert_run(50, ago(hours=4), sent=True)], updated_at=ago(hours=2), update_runs=[run_dict(3, "waiting", ago(minutes=90))])
    assert do_check(world).alert is not None  # 4시간 전 경고는 사이트가 복구되기 전 정체의 것 (updatedAt은 2시간 전)


def test_the_current_run_is_ignored_when_reading_history():
    prev = [alert_run(99, ago(minutes=1), sent=True)]  # 이번 실행 자신(GITHUB_RUN_ID)이 목록에 보이는 경우
    assert do_check(stale_world(prev), current_run_id="99").alert is not None


def test_runs_older_than_the_window_are_not_inspected():
    world = stale_world([alert_run(50, ago(hours=9), sent=True)])
    do_check(world)
    assert not any("/runs/50/jobs" in c[1] for c in world.github_calls)  # 7시간보다 오래된 실행은 jobs를 조회하지 않는다


def test_only_the_newest_alert_run_is_inspected_for_jobs():
    world = stale_world([alert_run(52, ago(hours=1), sent=True), alert_run(51, ago(hours=2), sent=True), alert_run(50, ago(hours=3), sent=True)])
    do_check(world)
    assert [c[1].split("/runs/")[1].split("/")[0] for c in world.github_calls if c[1].endswith("per_page=10")] == ["52"]


def test_history_lookup_failure_leans_toward_alerting(caplog):
    world = stale_world([], fail={("GET", "/workflows/watchdog.yml/runs"): 500})
    with caplog.at_level(logging.WARNING):
        out = do_check(world)
    assert out.alert is not None and TOKEN not in caplog.text and "GitHub HTTP 500" in caplog.text


# ============================ 스크립트 (watchdog.py) ============================
def run_script(tmp_path, world, *argv, token=TOKEN, extra_env=None):
    out_file, alerts = tmp_path / "gh_output", tmp_path / "out" / "alerts.json"
    env = {"GITHUB_OUTPUT": str(out_file), "GITHUB_REPOSITORY": REPO, **({"GITHUB_TOKEN": token} if token else {}), **(extra_env or {})}
    code = script.main(list(argv), get=world.get, post=world.post, environ=env, now=NOW, alerts_file=alerts)
    return code, alerts, (out_file.read_text(encoding="utf-8") if out_file.exists() else "")


def test_script_healthy_writes_no_alert_file_and_reports_alert_false(tmp_path):
    code, alerts, output = run_script(tmp_path, make_world(updated_at=ago(minutes=20)))
    assert code == 0 and not alerts.exists() and output == "alert=false\n"


def test_script_stale_writes_an_alert_file_send_alerts_accepts(tmp_path):
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(111, "waiting", ago(minutes=61))])
    code, alerts, output = run_script(tmp_path, world)
    assert code == 0 and output == "alert=true\n" and world.cancelled
    doc = json.loads(alerts.read_text(encoding="utf-8"))
    assert doc["alertCount"] == 1 and send_alerts.load_messages(alerts) == doc["messages"]
    assert TOKEN not in alerts.read_text(encoding="utf-8")


def test_script_suppressed_repeat_reports_alert_false_and_leaves_no_file(tmp_path):
    code, alerts, output = run_script(tmp_path, stale_world([alert_run(50, ago(hours=1), sent=True)]))
    assert code == 0 and output == "alert=false\n" and not alerts.exists()


def test_script_deletes_a_leftover_alert_file_first(tmp_path):
    alerts = tmp_path / "out" / "alerts.json"
    alerts.parent.mkdir()
    alerts.write_text("{}", encoding="utf-8")  # 이전 실행이 남긴 파일이 이번(정상) 점검 뒤에 발송되면 안 된다
    code, _, output = run_script(tmp_path, make_world(updated_at=ago(minutes=20)))
    assert code == 0 and not alerts.exists() and output == "alert=false\n"


def test_script_dry_run_changes_nothing_and_prints_the_alert(tmp_path, capsys):
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(111, "waiting", ago(minutes=61))])
    code, alerts, output = run_script(tmp_path, world, "--dry-run")
    assert code == 0 and world.posts == [] and not alerts.exists() and output == "alert=false\n"
    assert "[디스코드 dry-run]" in capsys.readouterr().out


def test_script_unreadable_site_is_a_warning_annotation_not_a_failure(tmp_path, capsys):
    world = make_world(fail={("GET", "/data/news.json"): 500})
    code, alerts, output = run_script(tmp_path, world, extra_env={"GITHUB_ACTIONS": "true"})
    assert code == 0 and output == "alert=false\n" and not alerts.exists()
    assert "::warning title=사이트 감시::" in capsys.readouterr().out


def test_script_stale_adds_an_annotation_even_when_the_alert_is_suppressed(tmp_path, capsys):
    run_script(tmp_path, stale_world([alert_run(50, ago(hours=1), sent=True)]), extra_env={"GITHUB_ACTIONS": "true"})
    assert "::warning title=" in capsys.readouterr().out


def test_script_never_prints_or_logs_the_token(tmp_path, capsys, caplog):
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(3, "waiting", ago(minutes=61))],
                       fail={("POST", "/runs/3/cancel"): 500, ("GET", "/workflows/watchdog.yml/runs"): 500})
    with caplog.at_level(logging.DEBUG):
        run_script(tmp_path, world, extra_env={"GITHUB_ACTIONS": "true"})
        run_script(tmp_path, world, "--dry-run")
    captured = capsys.readouterr()
    assert TOKEN not in caplog.text and TOKEN not in captured.out and TOKEN not in captured.err


def test_the_token_only_travels_in_the_authorization_header(tmp_path):
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(3, "waiting", ago(minutes=61))])
    run_script(tmp_path, world)
    assert all(TOKEN not in url for _, url, _ in world.calls)
    assert all(h.get("Authorization") == f"Bearer {TOKEN}" for _, _, h in world.github_calls)
    assert all("Authorization" not in h for _, url, h in world.calls if "sora7942.github.io" in url)  # 사이트에는 토큰을 보내지 않는다


def test_script_ignores_the_discord_webhook_even_if_it_is_in_the_environment(tmp_path):
    hook = "https://discord.com/api/webhooks/123456789/SECRET-TOKEN-abcdef"
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(3, "waiting", ago(minutes=61))])
    _, alerts, _ = run_script(tmp_path, world, extra_env={"DISCORD_WEBHOOK_URL": hook})
    assert all("discord" not in url for _, url, _ in world.calls) and hook not in alerts.read_text(encoding="utf-8")


def test_neither_module_reads_the_webhook_secret():
    for path in (ROOT / "watchdog.py", ROOT / "updater" / "watchdog.py"):
        assert "DISCORD_WEBHOOK_URL" not in path.read_text(encoding="utf-8").replace("DISCORD_WEBHOOK_URL을 읽지 않는다", "")


def test_script_falls_back_to_the_default_repo_outside_actions(tmp_path):
    world = make_world(updated_at=ago(hours=22), update_runs=[run_dict(3, "waiting", ago(minutes=61))])
    out_file, alerts = tmp_path / "o", tmp_path / "out" / "alerts.json"
    script.main([], get=world.get, post=world.post, environ={"GITHUB_TOKEN": TOKEN}, now=NOW, alerts_file=alerts)
    assert any(f"/repos/{config.GITHUB_DEFAULT_REPO}/" in url for _, url, _ in world.github_calls)


# ============================ http.post_json 확장 ===============================
def test_post_json_accepts_extra_headers_and_a_bodyless_post():
    class S:
        calls = []

        def post(self, url, **kw):
            self.calls.append((url, kw))
            return make_response(202, b"{}")

    s = S()
    http.post_json("https://example.invalid/cancel", session=s, headers={"Authorization": "Bearer x"})
    (url, kw), = s.calls
    assert kw["json"] is None and kw["timeout"] == config.TIMEOUT and kw["headers"] == {"User-Agent": config.USER_AGENT, "Authorization": "Bearer x"}
