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

from updater import alerts, annotate, auto_events, config, discord, http, redact, shorts, state, tagging, timeutil
from updater.sources import chzzk, claude_events, stellive_music, stellive_news, youtube_api, youtube_avatar, youtube_rss

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
    youtube_api_ok: bool = False  # 이번 실행의 영상 수집이 전부 API로 됐는가 (키 없음·할당량 초과·키 거부면 False). 쇼츠 판별은 True일 때만 한다
    anthropic_api_key: str | None = None  # 공지 일정 추출(Claude)용. 없으면 그 단계만 건너뛴다. 로그·메시지에 절대 넣지 않는다
    claude_model: str = config.CLAUDE_DEFAULT_MODEL
    post: callable = http.post_json  # Claude 호출 통로 (테스트가 가짜를 주입한다). 디스코드 발송 수단이 아니다
    environ: dict = field(default_factory=dict)  # Actions 주석(::warning::) 출력 여부 판단용


@dataclass
class SourceResult:
    news_items: list = field(default_factory=list)
    catalog_items: list | None = None  # None = 이 소스는 catalog를 건드리지 않음 (빈 리스트 = 건드렸지만 새 곡 없음)
    status_patches: dict | None = None  # None = 이 소스는 status를 건드리지 않음. {멤버 key: {필드: 값}}
    errors: list = field(default_factory=list)
    failed: bool = False  # True = 소스 전체가 실패한 것으로 센다('모든 소스 실패' 판정). 그래도 status_patches는 병합한다(치지직 연속 실패 횟수)


def run_youtube(ctx: Context) -> SourceResult:
    """YouTube Data API가 기본. RSS는 ① 키가 없거나 ② 할당량이 초과됐거나 ③ 키가 거부됐을 때만, 그것도 API로 못 한 채널만 쓴다.
    ③은 사람이 조치해야 하므로 Actions 실행 요약에 ::warning:: 주석("YouTube API 키 확인 필요")을 남긴다.
    그 밖의 API 실패(5xx·네트워크 등)는 RSS로 돌리지 않고 해당 채널의 실패로 남긴다."""
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
        ctx.youtube_api_ok = not (res.quota_exceeded or res.key_rejected)
        log.info("유튜브: API로 %d개 채널 처리 (영상 %d개%s)", len(channels) - len(rss_channels), len(items),
                 f", 실패 {len(errors)}건" if errors else "")
        if res.quota_exceeded:
            log.warning("YouTube API 할당량 초과 — 남은 %d개 채널은 RSS로 수집합니다", len(rss_channels))
        if res.key_rejected:  # 상태·reason만 담긴다 (키 값 없음)
            log.warning("YouTube API 키 확인 필요 (%s) — 남은 %d개 채널은 RSS로 수집합니다", res.key_rejected, len(rss_channels))
            annotate.warning("YouTube API", f"YouTube API 키 확인 필요 ({res.key_rejected}) — 영상은 RSS로 대체 수집했습니다. "
                             "키가 맞는지, YouTube Data API v3가 켜져 있는지, 키 제한(IP·API)을 확인하세요", environ=ctx.environ)
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


def classify_shorts(ctx: Context, items: list) -> None:
    """병합된 news 항목의 쇼츠 판별 (updater/shorts.py, SPEC 5장). 병합 밖의 단계다: 기존 항목의 백필과 '정해지지 않은 항목의 재시도'가 필요해서
    (병합은 id가 같으면 기존 항목이 이긴다). 영상 수집이 API로 되지 않은 실행(RSS 대체)에서는 건너뛴다 — 키가 없거나 할당량이 바닥이거나 키가 거부된 상태다.
    부가 단계라서 여기서 무슨 일이 나도 실행(과 배포)을 멈추지 않는다. 판별되지 않은 항목은 다음 실행에 다시 시도한다."""
    if not ctx.youtube_api_ok:
        log.info("쇼츠 판별 건너뜀 — 영상을 YouTube API로 수집하지 않은 실행입니다 (다음 실행에 다시 시도)")
        return
    try:
        report = shorts.fill(items, youtube_rss.channels_from_members(ctx.members), api_key=ctx.youtube_api_key, now=ctx.now, get=ctx.get)
        log.info("%s", report.summary())
    except Exception as e:  # 예상 밖의 오류는 종류만 남긴다 (메시지에 URL이 있을 수 있다)
        log.warning("쇼츠 판별 중 오류(%s) — 건너뛰고 계속합니다", type(e).__name__)
        log.debug("쇼츠 판별 오류 상세", exc_info=True)


def run_events(ctx: Context, prev: dict, news_items: list) -> tuple[dict, list]:
    """병합된 news의 공지(sl-*)에서 일정을 뽑아 auto_events 문서를 갱신한다 (updater/auto_events.py, SPEC-v1.1 기능 3) → (새 문서, 이번에 새로 저장된 일정).
    부가 단계라서 여기서 무슨 일이 나도 실행(과 배포)을 멈추지 않는다. 키가 없거나 중간에 실패하면 이전 문서를 **그대로** 돌려준다 — 배포는 site/ 전체를
    올리므로, 문서를 쓰지 않으면 저장소의 빈 시드가 배포본의 누적 일정·처리 기록을 덮어쓴다."""
    kept = {"updatedAt": prev.get("updatedAt"), "processed": prev.get("processed") or {}, "items": prev.get("items") or []}
    if not ctx.anthropic_api_key:
        log.warning("%s가 없어 공지 일정 추출을 건너뜁니다 — 이전 일정은 그대로 유지합니다", config.ANTHROPIC_API_KEY_ENV)
        return kept, []
    try:
        client = claude_events.Client(ctx.anthropic_api_key, model=ctx.claude_model, post=ctx.post)
        res = auto_events.run(prev, news_items, members=ctx.members, index=ctx.index, client=client, now=ctx.now, now_iso=ctx.now_iso,
                              get=ctx.get, sleep=ctx.sleep)
    except Exception as e:  # 예상 밖의 오류는 종류만 남긴다 (메시지에 URL이 있을 수 있다)
        log.warning("공지 일정 추출 중 오류(%s) — 건너뛰고 계속합니다", type(e).__name__)
        log.debug("일정 추출 오류 상세", exc_info=True)
        return kept, []
    rep = res.report
    log.info("%s", rep.summary())
    if isinstance(rep.abort, claude_events.KeyRejected):  # 상태·error.type만 담겼다 (키·응답 본문 없음)
        annotate.warning("Claude API", f"Claude API 키 확인 필요 ({rep.abort}) — 공지 일정 추출을 건너뛰었습니다. 다음 실행에 다시 시도합니다. "
                         "Secret ANTHROPIC_API_KEY가 맞는지 확인하세요", environ=ctx.environ)
    elif isinstance(rep.abort, claude_events.RequestRejected):
        annotate.warning("Claude API", f"Claude API가 요청을 거부했습니다 ({rep.abort}) — 공지 일정 추출을 건너뛰었습니다. 크레딧 잔액·모델 이름을 확인하세요",
                         environ=ctx.environ)
    doc = {"updatedAt": ctx.now_iso, "processed": res.doc["processed"], "items": res.doc["items"]}
    return doc, res.fresh


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
    def warn_streak(name: str, streak: int, reason: str) -> None:
        # 같은 멤버가 연속으로 실패하는 중 — 이 멤버의 LIVE 표시와 방송 시작 알림이 갱신되지 않고 있다. 사람이 볼 수 있게 실행 요약에 올린다
        log.warning("치지직 %s: %d회 연속 실패 (%s) — LIVE 표시·방송 시작 알림이 갱신되지 않습니다", name, streak, reason)
        annotate.warning("치지직", f"{name}: 치지직 확인이 {streak}회 연속 실패했습니다 ({reason}) — 이 멤버의 LIVE 표시와 방송 시작 알림이 누락되고 있습니다",
                         environ=ctx.environ)

    patches, errors = chzzk.collect(ctx.members["members"], now_iso=ctx.now_iso, prev_status=ctx.prev_status, on_streak=warn_streak,
                                    get=ctx.get, sleep=ctx.sleep)
    all_failed = bool(errors) and not any("live" in p for p in patches.values())
    if all_failed:
        # 전부 실패 = 차단·API 변경 가능성. 소스 실패로 세고(다른 소스도 다 실패하면 실행이 중단된다) 이전 live 값은 그대로 유지된다(패치에
        # live가 없다). 예외로 끝내지 않는 이유: 연속 실패 횟수(liveFails)를 저장해야 차단이 길어질 때 경고가 나온다
        log.error("소스 chzzk 실패: 모든 멤버 실패 (%d명): %s", len(errors), errors[0])
    return SourceResult(status_patches=patches, errors=errors, failed=all_failed)


# 이름 → 실행 함수 (실행 순서)
SOURCES = {"youtube": run_youtube, "news": run_news, "music": run_music, "avatar": run_avatar, "chzzk": run_chzzk}
# 수집기가 아니라 병합된 공지에서 일정을 뽑는 병합 뒤 단계 (기능 3). --only와 config.ENABLED_SOURCES에서는 소스처럼 이름으로 고른다
STAGE_EVENTS = "events"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="스텔라 레이더 업데이터")
    p.add_argument("--dry-run", action="store_true", help="데이터 파일은 쓰되 알림 파일은 남기지 않고, 보낼 내용을 콘솔에 출력한다")
    p.add_argument("--no-discord", action="store_true", help="알림을 남기지 않는다 (발송 단계가 보낼 것이 없게 된다)")
    p.add_argument("--only", help=f"쉼표로 구분한 소스만 실행 ({', '.join(SOURCES)}, {STAGE_EVENTS})")
    p.add_argument("--local-state", action="store_true", help="이전 상태를 배포본 대신 로컬 site/data/에서 읽는다")
    args = p.parse_args(argv)
    names = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else list(config.ENABLED_SOURCES)
    unknown = [n for n in names if n not in SOURCES and n != STAGE_EVENTS]
    if unknown:
        p.error(f"알 수 없는 소스: {', '.join(unknown)} (가능: {', '.join([*SOURCES, STAGE_EVENTS])})")
    args.sources = [n for n in SOURCES if n in names]  # 항상 정해진 실행 순서대로
    args.events = STAGE_EVENTS in names  # 공지 일정 추출 (병합 뒤 단계)
    return args


def discard_pending_alerts(alerts_file: Path) -> None:
    """이전 실행이 남긴 알림 파일을 지운다. 이 실행이 중간에 실패하거나 알림이 없어도 옛 알림이 나가지 않게 매 실행 맨 처음에 한다."""
    try:
        alerts_file.unlink(missing_ok=True)
    except OSError as e:
        log.warning("이전 알림 파일을 지우지 못했습니다(%s) — 발송 단계가 옛 알림을 보낼 수 있습니다", type(e).__name__)


def notify(args, members: dict, fresh: list, prev_status: dict, new_status: dict, now: datetime, now_iso: str, alerts_file: Path,
           fresh_events: list = (), news_items: list = ()) -> None:
    """알림 대상을 고르고 → dry-run이면 콘솔에 출력만, 아니면 보낼 내용을 alerts_file에 남긴다 (발송은 배포 성공 뒤 send_alerts.py).
    알림은 부가 기능이다 — 여기서 무슨 일이 나도 실행(과 배포)을 멈추지 않는다."""
    try:
        todo = alerts.build_alerts(fresh, prev_status, new_status, now, fresh_events=fresh_events, news_items=news_items)
        counts = {k: sum(a["kind"] == k for a in todo) for k in alerts.KIND_ORDER}
        log.info("알림 대상 %d건 (새 항목 %d건·새 일정 %d건 중) — 방송 %d · 공지 %d · 일정 %d · 새 곡 %d · 영상 %d",
                 len(todo), len(fresh), len(fresh_events), counts["live"], counts["notice"], counts["event"], counts["music"], counts["video"])
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
    claude_post=http.post_json,  # Claude 호출 통로(테스트가 가짜를 주입한다). 디스코드 발송 수단이 아니다 — main.py는 디스코드로 보내지 않는다
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
    claude_key = (environ.get(config.ANTHROPIC_API_KEY_ENV) or "").strip() or None
    redact.register(claude_key)
    data_dir = Path(data_dir)
    alerts_file = Path(alerts_file or config.ALERTS_FILE)  # 호출 시점에 읽는다 (테스트가 바꿀 수 있게)
    discard_pending_alerts(alerts_file)
    started = now()
    now_iso = timeutil.to_kst_iso(started)  # 이번 실행의 기준 시각 (added·updatedAt의 값)

    members = state.read_json(data_dir / "members.json")
    ctx = Context(members=members, index=tagging.build_index(members), now=started, now_iso=now_iso, get=get, sleep=sleep,
                  youtube_api_key=api_key, environ=environ, anthropic_api_key=claude_key, post=claude_post,
                  claude_model=(environ.get(config.CLAUDE_MODEL_ENV) or "").strip() or config.CLAUDE_DEFAULT_MODEL)

    def load(name):
        return state.load_previous(name, local_dir=data_dir, get=get, sleep=sleep, local_only=args.local_state)

    try:
        prev_news = load("news")
        if "music" in args.sources:  # 음악을 안 돌릴 때는 catalog 상태가 필요 없다
            ctx.prev_catalog = load("catalog")["items"]
        # 아바타·방송 상태·(API로 도는) 유튜브만 status 상태가 필요하다 (업로드 재생목록 ID 캐시)
        if {"avatar", "chzzk"} & set(args.sources) or ("youtube" in args.sources and api_key):
            ctx.prev_status = load("status")["members"]
        if args.events:
            prev_events = load("auto_events")
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

    if args.sources and not any(not r.failed for r in results.values()):  # 수집기를 하나도 안 돌린 실행(--only events)은 해당 없음
        log.error("모든 소스가 실패해 중단합니다 (파일을 쓰지 않습니다)")
        return 1

    collected = [it for r in results.values() for it in r.news_items]
    merged, fresh = state.merge_news(prev_news["items"], collected, now_iso=now_iso)
    if "youtube" in results:  # fresh 항목은 merged와 같은 객체라서, 여기서 채운 short를 알림 판정도 본다
        classify_shorts(ctx, merged)
    if args.sources:  # 수집기를 하나도 안 돌린 실행(--only events)은 소식을 다시 쓰지 않는다 (updatedAt이 '방금 수집했다'로 거짓이 된다)
        state.write_json(data_dir / "news.json", {"updatedAt": now_iso, "items": merged})
        log.info("news.json: 전체 %d개 (새 항목 %d개) · updatedAt %s", len(merged), len(fresh), now_iso)
        for it in fresh[:10]:
            log.info("  + [%s] %s — %s", it["cat"], it["title"], it["id"])
        if len(fresh) > 10:
            log.info("  … 외 %d건", len(fresh) - 10)

    fresh_events: list = []
    if args.events:  # 병합된 news의 공지에서 일정 추출. 키가 없거나 실패해도 이전 문서를 그대로 쓴다 (배포가 시드로 덮어쓰지 않게)
        events_doc, fresh_events = run_events(ctx, prev_events, merged)
        state.write_json(data_dir / "auto_events.json", events_doc)
        log.info("auto_events.json: 일정 %d개 (이번 +%d개) · 처리한 공지 %d개", len(events_doc["items"]), len(fresh_events), len(events_doc["processed"]))

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
    notify(args, members, fresh, ctx.prev_status, members_status, started, now_iso, alerts_file, fresh_events=fresh_events, news_items=merged)
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for stream in (sys.stdout, sys.stderr):  # Windows 기본 콘솔(cp949)에서 한글·특수문자가 깨지거나 예외가 나는 것을 막는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
