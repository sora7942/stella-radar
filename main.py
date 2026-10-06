"""stella-radar 업데이터. 수집 → site/data/ 갱신 → (보낼 알림을 out/alerts.json에 남김).

    python main.py --dry-run                      # 파일은 쓰되 알림 파일은 남기지 않고, 보낼 내용을 콘솔에 출력한다
    python main.py --no-discord                   # 알림을 남기지 않는다 (출력도 없음)
    python main.py --dry-run --only youtube,news  # 일부 소스만
    python main.py --local-state                  # 이전 상태를 배포본 대신 로컬 site/data/에서 읽는다 (로컬 반복 실험용)

**이 스크립트는 디스코드로 보내지 않는다.** 알림은 배포가 성공한 뒤에 나가야 하므로(배포가 실패했는데 알림만 나가면 다음 실행에서
같은 항목이 다시 '새 것'이 되어 중복 알림이 난다), 보낼 알림을 site/ 밖의 파일(config.ALERTS_FILE)에 남기고
배포 성공 후 단계가 `python send_alerts.py`로 그 파일만 읽어 발송한다. 웹훅 URL(DISCORD_WEBHOOK_URL)은 그 단계만 쓴다.
이 파일은 매 실행 시작에 지운다 — 이전 실행의 알림이나 dry-run의 알림이 나중에 실수로 나가지 않게.

종료 코드: 0 = 정상(일부 소스 실패는 로그만 남기고 계속), 1 = 계속하면 데이터가 망가질 상황(이전 상태 읽기 실패, 모든 소스 실패),
2 = 인자 오류. 1이면 파일을 쓰지 않으므로 워크플로는 배포를 건너뛴다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from updater import alerts, config, discord, http, redact, state, tagging, timeutil
from updater.sources import chzzk, stellive_music, stellive_news, youtube_api, youtube_avatar, youtube_rss

log = logging.getLogger("main")


@dataclass
class Context:
    members: dict
    index: tagging.TagIndex
    now: datetime
    now_iso: str
    get: callable
    sleep: callable
    prev_catalog: list = field(default_factory=list)
    prev_status: dict = field(default_factory=dict)  # status.json의 이전 'members'
    youtube_api_key: str | None = None  # 없으면 RSS로 수집한다. 로그·메시지에 절대 넣지 않는다


@dataclass
class SourceResult:
    news_items: list = field(default_factory=list)
    catalog_items: list | None = None  # None = 이 소스는 catalog를 건드리지 않음 (빈 리스트 = 건드렸지만 새 곡 없음)
    status_patches: dict | None = None  # None = 이 소스는 status를 건드리지 않음. {멤버 key: {필드: 값}}, 성공한 멤버만
    errors: list = field(default_factory=list)


def run_youtube(ctx: Context) -> SourceResult:
    """YouTube Data API가 기본, RSS는 키가 없거나 할당량이 초과됐을 때만 (남은 채널만) 쓴다.
    그 밖의 API 실패(키 거부 등)는 RSS로 돌리지 않고 해당 채널의 실패로 남긴다."""
    channels = youtube_rss.channels_from_members(ctx.members)
    items: list = []
    errors: list = []
    patches: dict = {}
    rss_channels = channels
    if ctx.youtube_api_key:
        cached = {k: v["uploads"] for k, v in ctx.prev_status.items() if isinstance(v, dict) and v.get("uploads")}
        res = youtube_api.collect(channels, ctx.index, api_key=ctx.youtube_api_key, cached=cached, get=ctx.get)
        items, errors = list(res.items), list(res.errors)
        patches = {key: {"uploads": playlist} for key, playlist in res.uploads.items()}
        rss_channels = res.remaining
        log.info("유튜브: API로 %d개 채널 처리 (영상 %d개%s)", len(channels) - len(rss_channels), len(items),
                 f", 실패 {len(errors)}건" if errors else "")
        if res.quota_exceeded:
            log.warning("YouTube API 할당량 초과 — 남은 %d개 채널은 RSS로 수집합니다", len(rss_channels))
    else:
        log.info("YOUTUBE_API_KEY가 없어 RSS로 수집합니다")
    if rss_channels:
        rss_items, rss_errors = youtube_rss.collect(rss_channels, ctx.index, get=ctx.get, sleep=ctx.sleep)
        have = {it["id"] for it in items}
        items += [it for it in rss_items if it["id"] not in have]  # API로 받은 항목이 먼저
        errors += rss_errors
    if errors and not items:
        raise RuntimeError(f"모든 채널 실패 ({len(errors)}건): {errors[0]}")
    return SourceResult(news_items=items, status_patches=patches or None, errors=errors)


def run_news(ctx: Context) -> SourceResult:
    return SourceResult(news_items=stellive_news.collect(ctx.index, get=ctx.get))


def run_music(ctx: Context) -> SourceResult:
    res = stellive_music.collect(ctx.prev_catalog, ctx.index, now=ctx.now, get=ctx.get, sleep=ctx.sleep)
    return SourceResult(
        news_items=res.news_items,
        catalog_items=res.catalog_items,
        errors=[f"상세 읽기 실패: {i}" for i in res.failed],
    )


def run_avatar(ctx: Context) -> SourceResult:
    patches, errors = youtube_avatar.collect(
        ctx.members["members"], ctx.prev_status, now=ctx.now, now_iso=ctx.now_iso, get=ctx.get, sleep=ctx.sleep
    )
    if errors and not patches:
        raise RuntimeError(f"모든 멤버 실패 ({len(errors)}명): {errors[0]}")
    return SourceResult(status_patches=patches, errors=errors)


def run_chzzk(ctx: Context) -> SourceResult:
    patches, errors = chzzk.collect(ctx.members["members"], now_iso=ctx.now_iso, get=ctx.get, sleep=ctx.sleep)
    if errors and not patches:  # 전부 실패 = 차단·API 변경 가능성 → 소스 실패로 남기고 이전 값을 유지한다
        raise RuntimeError(f"모든 멤버 실패 ({len(errors)}명): {errors[0]}")
    return SourceResult(status_patches=patches, errors=errors)


# 이름 → 실행 함수 (실행 순서)
SOURCES = {"youtube": run_youtube, "news": run_news, "music": run_music, "avatar": run_avatar, "chzzk": run_chzzk}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="스텔라 레이더 업데이터")
    p.add_argument("--dry-run", action="store_true", help="데이터 파일은 쓰되 알림 파일은 남기지 않고, 보낼 내용을 콘솔에 출력한다")
    p.add_argument("--no-discord", action="store_true", help="알림을 남기지 않는다 (발송 단계가 보낼 것이 없게 된다)")
    p.add_argument("--only", help=f"쉼표로 구분한 소스만 실행 ({', '.join(SOURCES)})")
    p.add_argument("--local-state", action="store_true", help="이전 상태를 배포본 대신 로컬 site/data/에서 읽는다")
    args = p.parse_args(argv)
    names = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else list(config.ENABLED_SOURCES)
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        p.error(f"알 수 없는 소스: {', '.join(unknown)} (가능: {', '.join(SOURCES)})")
    args.sources = [n for n in SOURCES if n in names]  # 항상 정해진 실행 순서대로
    return args


def discard_pending_alerts(alerts_file: Path) -> None:
    """이전 실행이 남긴 알림 파일을 지운다. 이 실행이 중간에 실패하거나 알림이 없어도 옛 알림이 나가지 않게 매 실행 맨 처음에 한다."""
    try:
        alerts_file.unlink(missing_ok=True)
    except OSError as e:
        log.warning("이전 알림 파일을 지우지 못했습니다(%s) — 발송 단계가 옛 알림을 보낼 수 있습니다", type(e).__name__)


def notify(args, members: dict, fresh: list, prev_status: dict, new_status: dict, now: datetime, now_iso: str, alerts_file: Path) -> None:
    """알림 대상을 고르고 → dry-run이면 콘솔에 출력만, 아니면 보낼 내용을 alerts_file에 남긴다 (발송은 배포 성공 뒤 send_alerts.py).
    알림은 부가 기능이다 — 여기서 무슨 일이 나도 실행(과 배포)을 멈추지 않는다."""
    try:
        todo = alerts.build_alerts(fresh, prev_status, new_status, now)
        counts = {k: sum(a["kind"] == k for a in todo) for k in alerts.KIND_ORDER}
        log.info("알림 대상 %d건 (새 항목 %d건 중) — 방송 %d · 공지 %d · 새 곡 %d · 영상 %d",
                 len(todo), len(fresh), counts["live"], counts["notice"], counts["music"], counts["video"])
        messages = discord.build_messages(todo, members, site_url=config.site_url())
        if not messages:
            return
        if args.dry_run:
            print(discord.format_dry_run(messages))
            return
        if args.no_discord:
            log.info("--no-discord: 알림 %d건은 남기지 않습니다", len(todo))
            return
        alerts_file.parent.mkdir(parents=True, exist_ok=True)
        state.write_json(alerts_file, {"createdAt": now_iso, "alertCount": len(todo), "messages": messages})
        log.info("알림 %d건(메시지 %d개)을 %s에 남겼습니다 — 배포가 성공한 뒤 send_alerts.py가 보냅니다", len(todo), len(messages), alerts_file)
    except Exception as e:
        log.warning("알림 처리 중 오류(%s) — 알림만 건너뛰고 계속합니다", type(e).__name__)
        log.debug("알림 오류 상세", exc_info=True)


def main(
    argv=None,
    *,
    get=http.get,
    data_dir: Path | str = config.DATA_DIR,
    alerts_file: Path | str | None = None,
    now=timeutil.now_kst,
    sleep=time.sleep,
    environ=None,
) -> int:
    args = parse_args(argv)
    redact.configure_logging()  # 등록된 비밀(API 키)은 로그 출력 직전에 한 번 더 가린다
    environ = os.environ if environ is None else environ
    api_key = (environ.get(config.YOUTUBE_API_KEY_ENV) or "").strip() or None
    redact.register(api_key)
    data_dir = Path(data_dir)
    alerts_file = Path(alerts_file or config.ALERTS_FILE)  # 호출 시점에 읽는다 (테스트가 바꿀 수 있게)
    discard_pending_alerts(alerts_file)
    started = now()
    now_iso = timeutil.to_kst_iso(started)  # 이번 실행의 기준 시각 (added·updatedAt의 값)

    members = state.read_json(data_dir / "members.json")
    ctx = Context(members=members, index=tagging.build_index(members), now=started, now_iso=now_iso, get=get, sleep=sleep,
                  youtube_api_key=api_key)

    def load(name):
        return state.load_previous(name, local_dir=data_dir, get=get, sleep=sleep, local_only=args.local_state)

    try:
        prev_news = load("news")
        if "music" in args.sources:  # 음악을 안 돌릴 때는 catalog 상태가 필요 없다
            ctx.prev_catalog = load("catalog")["items"]
        # 아바타·방송 상태·(API로 도는) 유튜브만 status 상태가 필요하다 (업로드 재생목록 ID 캐시)
        if {"avatar", "chzzk"} & set(args.sources) or ("youtube" in args.sources and api_key):
            ctx.prev_status = load("status")["members"]
    except state.StateLoadError as e:
        log.error("이전 상태를 읽지 못해 중단합니다 (배포는 건너뜁니다): %s", e)
        return 1

    results: dict[str, SourceResult] = {}
    for i, name in enumerate(args.sources):
        if i:
            sleep(config.REQUEST_DELAY)  # 소스 사이에도 간격 (같은 사이트에 연달아 가지 않게)
        try:
            results[name] = SOURCES[name](ctx)
            r = results[name]
            log.info("소스 %s: 소식 %d개%s%s%s", name, len(r.news_items),
                     f", 새 곡 {len(r.catalog_items)}개" if r.catalog_items is not None else "",
                     f", 멤버 상태 {len(r.status_patches)}명" if r.status_patches is not None else "",
                     f", 일부 실패 {len(r.errors)}건" if r.errors else "")
        except Exception as e:  # 소스 하나의 실패가 전체를 멈추지 않는다 (해당 소스의 이전 데이터는 그대로 남는다)
            log.error("소스 %s 실패: %s: %s", name, type(e).__name__, redact.mask(str(e)))  # 예외 메시지에 비밀이 섞였더라도 가린다

    if not results:
        log.error("모든 소스가 실패해 중단합니다 (파일을 쓰지 않습니다)")
        return 1

    collected = [it for r in results.values() for it in r.news_items]
    merged, fresh = state.merge_news(prev_news["items"], collected, now_iso=now_iso)
    state.write_json(data_dir / "news.json", {"updatedAt": now_iso, "items": merged})
    log.info("news.json: 전체 %d개 (새 항목 %d개) · updatedAt %s", len(merged), len(fresh), now_iso)
    for it in fresh[:10]:
        log.info("  + [%s] %s — %s", it["cat"], it["title"], it["id"])
    if len(fresh) > 10:
        log.info("  … 외 %d건", len(fresh) - 10)

    music = results.get("music")
    if music is not None:
        catalog, new_songs = state.merge_catalog(ctx.prev_catalog, music.catalog_items or [])
        state.write_json(data_dir / "catalog.json", {"updatedAt": now_iso, "items": catalog})
        log.info("catalog.json: 전체 %d곡 (이번 +%d곡)", len(catalog), len(new_songs))

    members_status = ctx.prev_status
    patches = [r.status_patches for r in results.values() if r.status_patches is not None]
    if patches:  # 아바타·치지직 중 하나라도 돌았을 때만 쓴다 (성공한 멤버만 바뀌고 나머지는 이전 값 유지)
        for patch in patches:
            members_status = state.merge_status(members_status, patch)
        state.write_json(data_dir / "status.json", {"updatedAt": now_iso, "members": members_status})
        live_now = [k for k, v in members_status.items() if v.get("live", {}).get("on")]
        log.info("status.json: 멤버 %d명 · 방송 중 %s", len(members_status), ", ".join(live_now) or "없음")

    # 파일을 다 쓴 뒤에 알린다. 이전/새 status가 같으면(치지직을 안 돌렸거나 전부 실패) 방송 알림은 나오지 않는다
    notify(args, members, fresh, ctx.prev_status, members_status, started, now_iso, alerts_file)
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글·특수문자가 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
