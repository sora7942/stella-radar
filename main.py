"""stella-radar 업데이터. 수집 → site/data/ 갱신 (→ 디스코드 발송: 5단계에서 추가).

    python main.py --dry-run                      # 파일은 쓰되 디스코드로는 보내지 않는다
    python main.py --dry-run --only youtube,news  # 일부 소스만
    python main.py --local-state                  # 이전 상태를 배포본 대신 로컬 site/data/에서 읽는다 (로컬 반복 실험용)

종료 코드: 0 = 정상(일부 소스 실패는 로그만 남기고 계속), 1 = 계속하면 데이터가 망가질 상황(이전 상태 읽기 실패, 모든 소스 실패),
2 = 인자 오류. 1이면 파일을 쓰지 않으므로 워크플로는 배포를 건너뛴다.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from updater import config, http, state, tagging, timeutil
from updater.sources import chzzk, stellive_music, stellive_news, youtube_avatar, youtube_rss

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


@dataclass
class SourceResult:
    news_items: list = field(default_factory=list)
    catalog_items: list | None = None  # None = 이 소스는 catalog를 건드리지 않음 (빈 리스트 = 건드렸지만 새 곡 없음)
    status_patches: dict | None = None  # None = 이 소스는 status를 건드리지 않음. {멤버 key: {필드: 값}}, 성공한 멤버만
    errors: list = field(default_factory=list)


def run_youtube(ctx: Context) -> SourceResult:
    channels = youtube_rss.channels_from_members(ctx.members)
    items, errors = youtube_rss.collect(channels, ctx.index, get=ctx.get, sleep=ctx.sleep)
    if errors and not items:
        raise RuntimeError(f"모든 채널 실패 ({len(errors)}개): {errors[0]}")
    return SourceResult(news_items=items, errors=errors)


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
    patches, errors = chzzk.collect(ctx.members["members"], get=ctx.get, sleep=ctx.sleep)
    if errors and not patches:  # 전부 실패 = 차단·API 변경 가능성 → 소스 실패로 남기고 이전 값을 유지한다
        raise RuntimeError(f"모든 멤버 실패 ({len(errors)}명): {errors[0]}")
    return SourceResult(status_patches=patches, errors=errors)


# 이름 → 실행 함수 (실행 순서)
SOURCES = {"youtube": run_youtube, "news": run_news, "music": run_music, "avatar": run_avatar, "chzzk": run_chzzk}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="스텔라 레이더 업데이터")
    p.add_argument("--dry-run", action="store_true", help="파일은 쓰되 디스코드로 보내지 않는다")
    p.add_argument("--no-discord", action="store_true", help="디스코드 발송을 끈다")
    p.add_argument("--only", help=f"쉼표로 구분한 소스만 실행 ({', '.join(SOURCES)})")
    p.add_argument("--local-state", action="store_true", help="이전 상태를 배포본 대신 로컬 site/data/에서 읽는다")
    args = p.parse_args(argv)
    names = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else list(config.ENABLED_SOURCES)
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        p.error(f"알 수 없는 소스: {', '.join(unknown)} (가능: {', '.join(SOURCES)})")
    args.sources = [n for n in SOURCES if n in names]  # 항상 정해진 실행 순서대로
    return args


def main(
    argv=None,
    *,
    get=http.get,
    data_dir: Path | str = config.DATA_DIR,
    now=timeutil.now_kst,
    sleep=time.sleep,
) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    data_dir = Path(data_dir)
    started = now()
    now_iso = timeutil.to_kst_iso(started)  # 이번 실행의 기준 시각 (added·updatedAt의 값)

    members = state.read_json(data_dir / "members.json")
    ctx = Context(members=members, index=tagging.build_index(members), now=started, now_iso=now_iso, get=get, sleep=sleep)

    def load(name):
        return state.load_previous(name, local_dir=data_dir, get=get, sleep=sleep, local_only=args.local_state)

    try:
        prev_news = load("news")
        if "music" in args.sources:  # 음악을 안 돌릴 때는 catalog 상태가 필요 없다
            ctx.prev_catalog = load("catalog")["items"]
        if {"avatar", "chzzk"} & set(args.sources):  # 아바타·방송 상태를 안 돌릴 때는 status 상태가 필요 없다
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
            log.error("소스 %s 실패: %s: %s", name, type(e).__name__, e)

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

    patches = [r.status_patches for r in results.values() if r.status_patches is not None]
    if patches:  # 아바타·치지직 중 하나라도 돌았을 때만 쓴다 (성공한 멤버만 바뀌고 나머지는 이전 값 유지)
        members_status = ctx.prev_status
        for patch in patches:
            members_status = state.merge_status(members_status, patch)
        state.write_json(data_dir / "status.json", {"updatedAt": now_iso, "members": members_status})
        live_now = [k for k, v in members_status.items() if v.get("live", {}).get("on")]
        log.info("status.json: 멤버 %d명 · 방송 중 %s", len(members_status), ", ".join(live_now) or "없음")
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글·특수문자가 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
