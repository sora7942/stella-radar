"""배포가 성공한 뒤 알림을 디스코드로 보낸다 (SPEC 7·9장).

    python send_alerts.py            # config.ALERTS_FILE(out/alerts.json)의 알림을 DISCORD_WEBHOOK_URL로 발송
    python send_alerts.py --dry-run  # 보낼 내용만 출력한다 (발송 안 함, 파일 유지)

main.py가 남긴 알림 파일**만** 읽는다. 수집한 데이터·상태·members.json은 보지 않으므로, 업데이터와 따로 돌려도(워크플로에서
deploy 성공 후 단계로) 같은 알림이 나간다. 웹훅 URL(DISCORD_WEBHOOK_URL)은 이 스크립트만 쓰고 어디에도 출력·로그로 남기지 않는다.

알림은 **최대 한 번** 나간다. 발송을 시도한 뒤에는 파일을 지워서(성공·실패 모두) 다시 돌려도 중복 발송되지 않는다. 대신 발송에
실패한 알림은 다시 시도하지 않는다(배포는 이미 끝나 다음 실행이 그 항목을 '이미 본 것'으로 보기 때문).

종료 코드는 항상 0이다 — 배포가 이미 끝났으므로 디스코드 문제로 실행을 실패로 만들지 않는다. 대신 문제는 경고 로그로 남기고,
GitHub Actions에서는 `::warning::` 주석으로도 내보내 실행 요약에서 보이게 한다 (예: Secret 미등록).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from updater import annotate, config, discord, http, redact

log = logging.getLogger("send_alerts")


class AlertsFileError(ValueError):
    """알림 파일이 예상한 모양이 아니다."""


def load_messages(path: Path) -> list[dict]:
    """알림 파일 → 웹훅 페이로드 목록. 모양이 이상하면 AlertsFileError (잘못된 파일을 그대로 디스코드로 보내지 않는다)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    messages = doc.get("messages") if isinstance(doc, dict) else None
    if not isinstance(messages, list):
        raise AlertsFileError("messages 목록이 없음")
    if len(messages) > config.DISCORD_MAX_MESSAGES:
        raise AlertsFileError(f"메시지가 {config.DISCORD_MAX_MESSAGES}개를 넘음")
    for m in messages:
        embeds = m.get("embeds") if isinstance(m, dict) else None
        if not isinstance(embeds, list) or not embeds or len(embeds) > config.DISCORD_EMBEDS_PER_MESSAGE:
            raise AlertsFileError("임베드 목록이 올바르지 않음")
        if not all(isinstance(e, dict) for e in embeds):
            raise AlertsFileError("임베드가 객체가 아님")
    return messages


def main(argv=None, *, post=http.post_json, sleep=time.sleep, alerts_file: Path | str | None = None, environ=None) -> int:
    p = argparse.ArgumentParser(description="알림 파일의 알림을 디스코드로 보낸다")
    p.add_argument("--dry-run", action="store_true", help="보낼 내용만 출력한다 (발송 안 함, 파일 유지)")
    args = p.parse_args(argv)
    redact.configure_logging()  # 웹훅 URL은 등록해 두면 로그 출력 직전에 한 번 더 가려진다
    environ = os.environ if environ is None else environ
    path = Path(alerts_file or config.ALERTS_FILE)  # 호출 시점에 읽는다 (테스트가 바꿀 수 있게)

    def warn(text: str) -> None:  # text에는 웹훅 URL이 들어가면 안 된다
        log.warning(text)
        annotate.warning("디스코드 알림", text, environ=environ)  # Actions 실행 요약에도 보이게

    if not path.exists():
        log.info("보낼 알림이 없습니다 (알림 파일 없음)")
        return 0
    try:
        messages = load_messages(path)
    except (OSError, ValueError) as e:  # JSON 오류 포함. 종류만 남긴다
        warn(f"알림 파일을 읽을 수 없어 보내지 않습니다 ({type(e).__name__})")
        return 0
    total = sum(len(m["embeds"]) for m in messages)

    if args.dry_run:
        print(discord.format_dry_run(messages))
        return 0

    webhook = environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        warn(f"DISCORD_WEBHOOK_URL이 없어 알림 {total}건을 보내지 못했습니다 — Secret 등록을 확인하세요")
        return 0  # 파일은 남겨 둔다 (웹훅을 설정한 뒤 다시 돌릴 수 있게)

    redact.register(webhook)
    sent, failed = discord.send(webhook, messages, post=post, sleep=sleep)
    log.info("디스코드: 메시지 %d개 발송, %d개 실패 (알림 %d건)", sent, failed, total)
    if failed:
        warn(f"디스코드 메시지 {failed}개를 보내지 못했습니다 (자세한 이유는 로그 참고)")
    try:
        path.unlink(missing_ok=True)  # 시도한 알림은 다시 보내지 않는다
    except OSError as e:
        warn(f"알림 파일을 지우지 못했습니다 ({type(e).__name__}) — 다시 실행하면 중복 발송될 수 있습니다")
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글이 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
