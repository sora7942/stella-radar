"""GitHub Actions 워크플로 구조 (SPEC 9장). 실제로 돌려 볼 수 없는 부분이라 '깨지면 안 되는 약속'을 파일 구조로 고정한다:
배포 성공 뒤에만 알림, Secret은 필요한 단계에만, 권한은 최소, 액션은 고정된 메이저 버전."""
import re

import pytest
import yaml

from conftest import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"


def load(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1은 `on`을 True로 읽는다
    return doc, text


@pytest.fixture(scope="module")
def update():
    return load("update.yml")


@pytest.fixture(scope="module")
def keepalive():
    return load("keepalive.yml")


@pytest.fixture(scope="module")
def watchdog():
    return load("watchdog.yml")


def steps_of(doc):
    (job,) = doc["jobs"].values()
    return job["steps"]


def find(steps, needle):
    (hit,) = [s for s in steps if needle in (s.get("uses", "") + s.get("run", ""))]
    return steps.index(hit), hit


# ============================ update.yml =====================================
def test_triggers_are_schedule_manual_and_push_to_main(update):
    on = update[0]["on"]
    assert on["schedule"] == [{"cron": "7,37 * * * *"}]
    minutes = sorted(int(m) for m in on["schedule"][0]["cron"].split()[0].split(","))
    assert minutes == [7, 37] and minutes[1] - minutes[0] == 30  # 30분 간격이지만 정각·30분(GitHub 고부하 시각)은 피한다
    assert on["push"]["branches"] == ["main"] and {"site/**", "updater/**"} <= set(on["push"]["paths"])
    assert on["workflow_dispatch"]["inputs"]["no_alerts"] == {"description": "디스코드 알림 없이 실행 (main.py --no-discord)", "type": "boolean", "default": False}
    assert set(on) == {"schedule", "workflow_dispatch", "push"}  # pull_request 계열 같은 다른 트리거는 없다


def test_runs_never_overlap_and_are_not_cancelled_midway(update):
    assert update[0]["concurrency"] == {"group": "pages", "cancel-in-progress": False}


def test_permissions_are_the_minimum_for_pages(update):
    assert update[0]["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}


def test_single_job_on_ubuntu_with_pages_environment_and_a_timeout(update):
    (job,) = update[0]["jobs"].values()
    assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] == 15  # 정상 실행은 몇 분. 오래 걸리는 실행은 멈춘 것
    assert job["environment"]["name"] == "github-pages" and "steps.deployment.outputs.page_url" in job["environment"]["url"]


def test_step_order_collect_then_deploy_then_alerts(update):
    steps = steps_of(update[0])
    order = [find(steps, n)[0] for n in ("actions/checkout", "actions/setup-python", "pip install", "python main.py", "upload-pages-artifact", "deploy-pages", "python send_alerts.py")]
    assert order == sorted(order) and len(set(order)) == 7
    assert order[-1] == len(steps) - 1  # 알림이 맨 마지막이다 (배포 뒤)


def test_alerts_only_run_when_every_earlier_step_succeeded(update):
    steps = steps_of(update[0])
    for s in steps:
        assert "continue-on-error" not in s, f"{s.get('name') or s.get('uses') or s.get('run')}: 실패를 삼키면 배포가 실패해도 알림 단계가 돈다"
        assert "if" not in s, "조건을 달면 앞 단계 실패 때도 돌 수 있다 (always()/failure())"


def test_the_deploy_step_has_the_id_the_environment_url_refers_to(update):
    _, deploy = find(steps_of(update[0]), "deploy-pages")
    assert deploy["id"] == "deployment"


def test_python_312_with_pip_cache_and_pages_artifact_is_the_site_folder(update):
    steps = steps_of(update[0])
    assert find(steps, "setup-python")[1]["with"] == {"python-version": "3.12", "cache": "pip"}
    assert find(steps, "upload-pages-artifact")[1]["with"] == {"path": "site"}  # site/ 밖(out/alerts.json)은 배포에 올라가지 않는다


def test_the_collect_step_takes_only_the_api_keys_and_the_alert_step_only_the_webhook(update):
    steps = steps_of(update[0])
    assert find(steps, "python main.py")[1]["env"] == {"YOUTUBE_API_KEY": "${{ secrets.YOUTUBE_API_KEY }}",
                                                         "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"}
    assert find(steps, "python send_alerts.py")[1]["env"] == {"DISCORD_WEBHOOK_URL": "${{ secrets.DISCORD_WEBHOOK_URL }}"}


def test_the_anthropic_key_is_in_the_main_py_step_only(update):
    """기능 3: 키를 읽는 것은 업데이터(main.py)뿐이다. 다른 단계(발송·배포·설치)와 워크플로·잡 수준에는 없다."""
    steps = steps_of(update[0])
    holders = [s.get("run") or s.get("uses") for s in steps if "ANTHROPIC_API_KEY" in (s.get("env") or {})]
    assert holders == [find(steps, "python main.py")[1]["run"]]
    assert update[1].count("ANTHROPIC_API_KEY") == 2  # 이름(env 키)과 secrets 참조 한 번씩


def test_secrets_are_referenced_nowhere_else(update):
    text = update[1]
    assert sorted(re.findall(r"secrets\.([A-Z_]+)", text)) == ["ANTHROPIC_API_KEY", "DISCORD_WEBHOOK_URL", "YOUTUBE_API_KEY"]
    assert "GITHUB_TOKEN" not in text and "secrets:" not in text and "inherit" not in text
    # job·workflow 수준 env에 비밀을 두면 모든 단계에 노출된다
    assert "env" not in update[0] and "env" not in next(iter(update[0]["jobs"].values()))


def test_the_manual_no_alerts_input_only_adds_the_no_discord_flag(update):
    run = find(steps_of(update[0]), "python main.py")[1]["run"]
    assert run == "python main.py ${{ inputs.no_alerts && '--no-discord' || '' }}"  # 입력 값을 셸에 그대로 끼워 넣지 않는다 (불리언 → 고정 문자열)


def test_every_official_action_is_pinned_to_a_major_version(update, keepalive, watchdog):
    uses = re.findall(r"uses:\s*(\S+)", update[1] + keepalive[1] + watchdog[1])
    assert uses and all(re.fullmatch(r"actions/[\w-]+@v\d+", u) for u in uses), uses
    assert {u.split("@")[0] for u in uses} == {"actions/checkout", "actions/setup-python", "actions/upload-pages-artifact", "actions/deploy-pages"}


def test_scripts_the_workflow_runs_exist_in_the_repo(update):
    for script in ("main.py", "send_alerts.py", "requirements.txt"):
        assert (ROOT / script).is_file()
        if script.endswith(".py"):
            assert f"python {script}" in update[1]


# ============================ keepalive.yml ==================================
def test_keepalive_runs_monthly_and_is_the_only_one_with_write_access(keepalive, update):
    on = keepalive[0]["on"]
    assert on["schedule"] == [{"cron": "17 3 1 * *"}] and "workflow_dispatch" in on and "push" not in on
    assert keepalive[0]["permissions"] == {"contents": "write"}
    assert update[0]["permissions"]["contents"] == "read"  # 배포 워크플로는 쓰기 권한이 없다


def test_keepalive_makes_an_empty_commit_and_uses_no_secrets(keepalive):
    run = "\n".join(s.get("run", "") for s in steps_of(keepalive[0]))
    assert "git commit --allow-empty" in run and "git push" in run
    assert "secrets." not in keepalive[1] and "${{" not in keepalive[1]  # 표현식 주입 여지가 없다


def test_the_keepalive_commit_cannot_trigger_the_update_workflow(keepalive, update):
    # 빈 커밋은 어떤 경로도 바꾸지 않으므로 update.yml의 paths 필터에 걸리지 않는다 (게다가 GITHUB_TOKEN push는 워크플로를 깨우지 않는다)
    assert "paths" in update[0]["on"]["push"] and "push" not in keepalive[0]["on"]


# ============================ watchdog.yml (기능 0-e) ==========================
def test_watchdog_is_manual_only_so_the_external_cron_is_the_only_caller(watchdog):
    on = watchdog[0]["on"]
    assert set(on) == {"workflow_dispatch"} and not (on["workflow_dispatch"] or {}).get("inputs")  # schedule·push 없음, 입력 없음(주입 여지 없음)


def test_watchdog_has_its_own_concurrency_group_so_it_runs_while_update_is_stuck(watchdog, update):
    assert watchdog[0]["concurrency"] == {"group": "watchdog", "cancel-in-progress": True}  # 점검 자신이 막히면 다음 점검이 대체한다
    assert watchdog[0]["concurrency"]["group"] != update[0]["concurrency"]["group"] == "pages"


def test_watchdog_permissions_are_only_actions_write_and_contents_read(watchdog):
    assert watchdog[0]["permissions"] == {"actions": "write", "contents": "read"}  # pages·id-token·contents:write 없음
    (job,) = watchdog[0]["jobs"].values()
    assert "permissions" not in job and "environment" not in job  # job 수준에서 권한을 넓히지 않는다. Pages 환경에도 묶이지 않는다


def test_only_keepalive_can_write_contents(keepalive, update, watchdog):
    assert keepalive[0]["permissions"]["contents"] == "write"
    assert update[0]["permissions"]["contents"] == "read" and watchdog[0]["permissions"]["contents"] == "read"


def test_watchdog_job_is_short_lived_on_ubuntu(watchdog):
    (job,) = watchdog[0]["jobs"].values()
    assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] <= 10


def test_watchdog_step_order_check_then_alert_last(watchdog):
    steps = steps_of(watchdog[0])
    order = [find(steps, n)[0] for n in ("actions/checkout", "actions/setup-python", "pip install", "python watchdog.py", "python send_alerts.py")]
    assert order == sorted(order) and len(set(order)) == 5 and order[-1] == len(steps) - 1


def test_the_alert_step_runs_only_when_the_check_asked_for_it_and_its_name_is_the_history_marker(watchdog):
    from updater import config
    steps = steps_of(watchdog[0])
    check, send = find(steps, "python watchdog.py")[1], find(steps, "python send_alerts.py")[1]
    assert check["id"] == "check" and send["if"] == "steps.check.outputs.alert == 'true'"
    # 이전 점검 실행에서 이 단계가 success였는지로 '경고를 이미 보냈는가'를 판단한다 — 이름이 바뀌면 중복 억제가 조용히 깨진다
    assert send["name"] == config.WATCHDOG_ALERT_STEP
    assert all("continue-on-error" not in s for s in steps)


def test_watchdog_secrets_each_go_to_exactly_one_step(watchdog):
    steps = steps_of(watchdog[0])
    assert find(steps, "python watchdog.py")[1]["env"] == {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    assert find(steps, "python send_alerts.py")[1]["env"] == {"DISCORD_WEBHOOK_URL": "${{ secrets.DISCORD_WEBHOOK_URL }}"}  # 웹훅은 발송 단계에만
    assert sorted(re.findall(r"secrets\.([A-Z_]+)", watchdog[1])) == ["DISCORD_WEBHOOK_URL", "GITHUB_TOKEN"]
    assert "YOUTUBE_API_KEY" not in watchdog[1] and "ANTHROPIC" not in watchdog[1]
    assert "env" not in watchdog[0] and "env" not in next(iter(watchdog[0]["jobs"].values()))  # workflow·job 수준 env 없음
    others = [s for s in steps if s not in (find(steps, "python watchdog.py")[1], find(steps, "python send_alerts.py")[1])]
    assert all("env" not in s for s in others)


def test_watchdog_uses_no_expression_injection_surface(watchdog):
    run_texts = "\n".join(s.get("run", "") for s in steps_of(watchdog[0]))
    assert "${{" not in run_texts  # run 본문에 컨텍스트 값을 끼워 넣지 않는다 (env로만 전달)


def test_watchdog_scripts_exist_and_python_is_312_with_pip_cache(watchdog):
    for script in ("watchdog.py", "send_alerts.py", "requirements.txt"):
        assert (ROOT / script).is_file()
    assert find(steps_of(watchdog[0]), "setup-python")[1]["with"] == {"python-version": "3.12", "cache": "pip"}


def test_watchdog_filename_matches_the_config_the_code_uses():
    from updater import config
    assert (WORKFLOWS / config.WATCHDOG_WORKFLOW_FILE).is_file() and (WORKFLOWS / config.UPDATE_WORKFLOW_FILE).is_file()
