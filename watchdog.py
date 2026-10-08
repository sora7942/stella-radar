"""갱신 정체 점검 (SPEC v1.1 기능 0-e, 규칙은 updater/watchdog.py).

    python watchdog.py            # 점검. 정체면 오래된 update 실행을 취소하고, 경고가 필요하면 out/alerts.json에 남긴다
    python watchdog.py --dry-run  # 읽기만 한다: 취소·파일 쓰기 없음, 하려는 일과 보낼 경고를 출력 (토큰 없이도 돈다)

디스코드로는 **보내지 않는다.** 경고는 send_alerts.py가 읽는 알림 파일(config.ALERTS_FILE)과 같은 형식으로 남기고, 워크플로의 다음 단계
("경고 발송", 웹훅 Secret은 그 단계의 env에만)가 `python send_alerts.py`로 보낸다. 이 스크립트는 DISCORD_WEBHOOK_URL을 읽지 않는다.
GITHUB_TOKEN(워크플로의 자동 토큰, actions: write)은 이 스크립트만 쓰고 헤더로만 보내며 로그에는 HTTP 상태만 남긴다.

Actions에서는 `alert=true|false`를 $GITHUB_OUTPUT에 써서 워크플로가 경고 발송 단계를 건너뛸지 정하게 한다.
이전 점검 실행의 "경고 발송" 단계가 success였는지가 곧 '경고를 이미 보냈는가'의 기록이다 (별도 상태 저장 없음).
종료 코드는 정상·정체·판정 불가 모두 0이다 (정체는 경고로 알린다). 예상 밖의 오류만 실패로 끝난다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from updater import annotate, config, discord, http, redact, state, timeutil, watchdog

log = logging.getLogger("watchdog")


def main(argv=None, *, get=http.get, post=http.post_json, environ=None, now=None, alerts_file: Path | str | None = None) -> int:
    p = argparse.ArgumentParser(description="사이트 갱신 정체를 점검한다")
    p.add_argument("--dry-run", action="store_true", help="읽기만 한다 (취소·파일 쓰기 없음)")
    args = p.parse_args(argv)
    redact.configure_logging()
    environ = os.environ if environ is None else environ
    now = now or timeutil.now_kst()
    path = Path(alerts_file or config.ALERTS_FILE)  # 호출 시점에 읽는다 (테스트가 바꿀 수 있게)

    token = (environ.get("GITHUB_TOKEN") or "").strip() or None
    redact.register(token)
    repo = (environ.get("GITHUB_REPOSITORY") or "").strip() or config.GITHUB_DEFAULT_REPO
    gh = watchdog.GitHub(repo, token, get=get, post=post)

    # 이전 실행(dry-run 포함)의 알림 파일이 이번 경고로 오해되어 나가지 않게 시작할 때 지운다
    if not args.dry_run:
        path.unlink(missing_ok=True)

    out = watchdog.check(now=now, gh=gh, site_url=config.site_url(), repo=repo, get=get,
                         current_run_id=environ.get("GITHUB_RUN_ID"), dry_run=args.dry_run)
    log.info("%s", out.reason)
    for run, result in out.stuck:
        log.info("  update 실행 #%s (%s, 시작 %s): %s", run.id, run.status, run.started.isoformat(timespec="seconds"), result)
    if out.runs_error:
        log.warning("update 실행 목록을 읽지 못했습니다 (%s)", out.runs_error)
    if out.state == "unknown":
        annotate.warning("사이트 감시", out.reason, environ=environ)
    elif out.state == "stale":
        annotate.warning("사이트 갱신 정체", out.reason, environ=environ)  # 경고 억제 중이어도 실행 요약에는 남긴다

    wrote = False
    if out.alert:
        if args.dry_run:
            print(discord.format_dry_run([out.alert]))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            state.write_json(path, {"createdAt": now.isoformat(timespec="seconds"), "alertCount": 1, "messages": [out.alert]})
            wrote = True
            log.info("경고 1건을 %s에 남겼습니다 — 다음 단계(send_alerts.py)가 보냅니다", path.name)

    output = environ.get("GITHUB_OUTPUT")
    if output:  # Actions: 다음 단계("경고 발송")를 돌릴지
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"alert={'true' if wrote else 'false'}\n")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글이 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
