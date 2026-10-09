"""URL·주기·개수 제한·알림 규칙은 전부 여기에만 둔다 (CLAUDE.md)."""
import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"

# --- 사이트 / 이전 상태 -------------------------------------------------------
DEFAULT_SITE_URL = "https://sora7942.github.io/stella-radar/"
STATE_FILES = ("news", "catalog", "status", "auto_events")  # 업데이터가 쓰는 파일 (이전 상태를 배포본에서 읽는다)
STATE_LOAD_ATTEMPTS = 3  # 404가 아닌 읽기 실패는 이만큼 재시도한 뒤 실행을 실패 처리한다
STATE_LOAD_BACKOFF = 1.0  # 초. 재시도마다 2배


def site_url() -> str:
    """환경변수 SITE_URL(.env 포함)이 있으면 그것을, 없으면 기본값. 항상 '/'로 끝난다."""
    url = os.environ.get("SITE_URL") or DEFAULT_SITE_URL
    return url if url.endswith("/") else url + "/"


# --- 시간 ----------------------------------------------------------------------
KST = timezone(timedelta(hours=9))

# --- HTTP ----------------------------------------------------------------------
TIMEOUT = 10  # 초. 모든 외부 요청에 강제
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_DELAY = 0.5  # 초. 같은 사이트에 연속 요청할 때 간격

# --- 수집 소스 -----------------------------------------------------------------
# 유튜브 새 영상: YouTube Data API가 기본이고, RSS는 API 키가 없거나 할당량이 초과됐을 때만 쓴다
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_API_KEY_ENV = "YOUTUBE_API_KEY"  # 환경변수 (GitHub Secret / 로컬 .env). 업데이터(main.py)만 읽는다
YOUTUBE_API_KEY_HEADER = "X-Goog-Api-Key"  # 키는 URL이 아니라 이 헤더로만 보낸다 (URL은 예외 메시지·로그에 남기 쉽다)
YOUTUBE_API_MAX_RESULTS = 15  # 채널당 최신 영상 수 (SPEC 5장)
# 업데이터가 부를 수 있는 API 엔드포인트(호출당 1유닛). search.list는 호출당 100유닛이라 여기 없고, 목록에 없는 엔드포인트는 요청 전에 거부된다
YOUTUBE_API_ENDPOINTS = ("channels", "playlistItems")
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# 쇼츠 판별 (updater/shorts.py, 기능 2): 채널 ID의 'UC'를 아래 접두어로 바꾸면 유튜브가 직접 분류한 재생목록이 된다 (playlistItems.list, 호출당 1유닛).
# 비공식 관례지만 2026-10-09 실측에서 12채널 모두 열렸고 UUSH+UULF가 전체 업로드와 309/309 일치했다 (PROGRESS 기능 2)
SHORTS_PLAYLIST_PREFIX = "UUSH"  # 쇼츠 탭
LONG_PLAYLIST_PREFIX = "UULF"  # 동영상(롱폼) 탭
SHORTS_PLAYLIST_RESULTS = 50  # 첫 페이지 크기(API 상한). 판별 대상은 채널의 최신 영상이라 첫 페이지면 충분하다
SHORTS_CONFIRM_HOURS = 24  # 처음 발견(added) 뒤 이 시간이 지나도 두 목록 어디에도 없으면 일반 영상(short:false)으로 확정 (라이브 다시보기·예약 영상 등)

OFFICIAL_SOURCE_LABEL = "공식 홈페이지"  # news 항목의 source 문구 (공지·음악 공통)

NEWS_URL = "https://stellive.me/news"
NEWS_ITEM_URL = "https://stellive.me/news/{number}"
NEWS_LIST_LIMIT = 30  # 목록 첫 페이지에 전체 360건이 있어 최신 N건만 쓴다 (사용자 결정)

MUSIC_URL = "https://stellive.me/music"
MUSIC_ITEM_URL = "https://stellive.me/music/{number}"
MUSIC_DETAIL_PER_RUN = 40  # 실행당 새로 가져오는 상세 페이지 수 (요청 간 REQUEST_DELAY)
MUSIC_TAB_MAX_PAGES = 30  # 분류 탭 한 개당 읽을 페이지 안전 상한. 넘으면 끝을 확인할 수 없으므로 실패 처리한다
MUSIC_FEED_DAYS = 14  # catalog에 처음 들어온 곡 중 발매일이 이 기간 안이면 news 피드에도 올린다

YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/{channel_id}"
AVATAR_REFRESH_HOURS = 24  # 프로필 사진(og:image)은 하루에 한 번만 다시 읽는다
# 저장하는 아바타 URL의 크기 파라미터(원본 `=s900-…` → `=s240-…`). 같은 서버의 같은 이미지를 작게 받을 뿐이다.
# 화면에서는 64px(고해상도 192px)로 쓴다
AVATAR_SIZE = 240
# og:image가 이 호스트일 때만 아바타로 인정한다 (동의·오류 페이지의 기본 이미지가 프로필로 들어가는 것 방지)
AVATAR_HOSTS = ("googleusercontent.com", "ggpht.com")

# 비공식 API. 앞에서부터 시도하고, HTTP 5xx일 때만 다음 후보로 넘어간다 (4xx·연결 오류·응답 형식 오류는 넘어가지 않는다).
# v2가 해외 IP(Actions)에서 방송 단위로 막히는 일이 있다: 후야 방송이 HTTP 500 code 9004 "해외 시청 불가능한 컨텐츠 입니다."로 막혔고,
# 같은 요청이 polling/v3에서는 200이었다(2026-10-07 Actions 시험). v3의 content는 v2와 키 51개가 같아 같은 파서를 쓴다
CHZZK_LIVE_STATUS_URLS = (
    "https://api.chzzk.naver.com/polling/v2/channels/{channel_id}/live-status",
    "https://api.chzzk.naver.com/polling/v3/channels/{channel_id}/live-status",
)
CHZZK_LIVE_STATUS_URL = CHZZK_LIVE_STATUS_URLS[0]  # 기본 엔드포인트
CHZZK_LIVE_PAGE_URL = "https://chzzk.naver.com/live/{channel_id}"
CHZZK_RETRY_5XX = 1  # 모든 후보가 5xx일 때 후보 전체를 이만큼 더 돈다 (그 전에 CHZZK_RETRY_DELAY초 대기)
CHZZK_RETRY_DELAY = 1.0  # 초
CHZZK_FAIL_WARN_STREAK = 3  # 같은 멤버의 확인이 이 횟수(실행 단위)만큼 연속 실패하면 Actions ::warning:: 주석

# 기본으로 돌리는 소스. 치지직이 Actions(해외 IP)에서 막히면 여기서 "chzzk"만 뺀다 (CLAUDE.md). --only는 이 목록과 무관하게 지정한 것만 돌린다
# "events"는 수집기가 아니라 병합된 공지에서 일정을 뽑는 병합 뒤 단계다 (기능 3). ANTHROPIC_API_KEY가 없으면 그 단계만 건너뛴다
ENABLED_SOURCES = ("youtube", "news", "music", "avatar", "chzzk", "events")

# --- 공지 일정 자동 추출 (기능 3, SPEC-v1.1) ---------------------------------------------
# Claude API는 이 기능에서만 쓴다. 호출은 requests로 직접(SDK 없음), 키는 x-api-key 헤더로만 보내고 로그·예외에는 HTTP 상태와 error.type만 남긴다
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"  # 환경변수 (GitHub Secret / 로컬 .env). 업데이터(main.py)만 읽는다
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"
CLAUDE_API_KEY_HEADER = "x-api-key"
CLAUDE_MODEL_ENV = "CLAUDE_MODEL"  # 모델을 바꾸고 싶을 때 (코드 수정 없이)
CLAUDE_DEFAULT_MODEL = "claude-haiku-4-5"
CLAUDE_MAX_TOKENS = 800
CLAUDE_TIMEOUT = 30  # 초. 모델 응답은 몇 초~십수 초 걸려서 TIMEOUT(10)보다 길다 — CLAUDE.md Rules의 유일한 예외
EVENTS_PER_RUN = 5  # 실행당 처리하는 공지 수 상한 (최대 비용을 묶는다). 최신 공지부터, error 재시도도 포함
EVENTS_WINDOW_DAYS = 45  # 공지 날짜가 오늘부터 이 일수 이내인 것만 대상 (달력 기준)
EVENTS_MAX_TRIES = 3  # 모델 출력이 깨져 error가 된 공지는 이 횟수까지만 다시 시도한다
EVENTS_BODY_MAX_CHARS = 6000  # 모델에 보내는 본문 상한
EVENTS_NO_TEXT_CHARS = 50  # 본문 글자 수(공백 제외)가 이보다 적으면 포스터 이미지뿐인 공지로 보고 API를 부르지 않는다 (no_text, 재시도 없음)
EVENTS_PER_NOTICE = 5  # 공지 하나에서 받아들이는 일정 수 상한
EVENT_TITLE_MAX = 60  # 일정 제목 길이 상한 (1~60자)
EVENT_TIME_MAX = 30  # 선택 필드 time(예: "10:00–20:00") 길이 상한
EVENT_PLACE_MAX = 60  # 선택 필드 place 길이 상한
EVENT_START_MIN_DAYS = -7  # start는 공지 날짜 기준 이 일수 이후부터
EVENT_START_MAX_DAYS = 365  # start는 공지 날짜 기준 이 일수 이내까지
EVENT_MAX_SPAN_DAYS = 366  # end는 start로부터 이 일수 이내 (환각으로 먼 미래의 end가 달력에 남는 것 방지)
EVENTS_KEEP_AFTER_END_DAYS = 30  # 끝난 지 이 일수가 넘은 자동 일정은 삭제
EVENTS_PROCESSED_KEEP_DAYS = 90  # processed 기록은 이 일수가 지나면 삭제
EVENT_KINDS = ("popup", "concert", "broadcast", "reservation", "goods", "other")
EVENT_ALERT_KINDS = ("popup", "concert", "reservation", "broadcast")  # 디스코드 '일정 추가' 알림 대상 (goods·other는 알리지 않는다)

# --- 소식 피드 -----------------------------------------------------------------
NEWS_MAX_ITEMS = 300  # news.json 보관 상한 (date 내림차순)

# --- 디스코드 알림 (SPEC 7장) -----------------------------------------------------
# '이번 실행에서 처음 본' 항목 중 아래 창 안에 있는 것만 알린다 (최초 실행 때 한꺼번에 쏟아지는 것·늦은 알림 방지)
ALERT_VIDEO_HOURS = 6  # 유튜브 영상: 게시 시각이 지금부터 이 시간 이내
ALERT_NOTICE_DAYS = 2  # 공식 공지: 날짜가 오늘부터 이 일수 이내 (달력 기준, 공지는 날짜만 있다)
MUSIC_ALERT_DAYS = 2  # 새 곡: 발매일이 오늘부터 이 일수 이내 (달력 기준)
# 방송 시작: since(방송 시작 시각)가 이전에 저장된 since와 다를 때만 새 방송이다. 그래도 since가 이보다 오래됐으면 늦은 알림이라 보내지 않는다.
# since가 없으면 이전 규칙(꺼짐→켜짐)을 쓴다
ALERT_LIVE_MAX_AGE_HOURS = 1

# 알림은 배포가 성공한 뒤에 보낸다. 업데이터(main.py)는 보낼 알림을 이 파일에 남기고, 배포 성공 후 단계가 send_alerts.py로 읽어 발송한다.
# site/ 밖이라 Pages에 올라가지 않고, 웹훅 URL도 들어 있지 않다. .gitignore 대상
ALERTS_DIR = ROOT / "out"
ALERTS_FILE = ALERTS_DIR / "alerts.json"

DISCORD_EMBEDS_PER_MESSAGE = 10  # 한 메시지의 임베드 상한 (디스코드 한도)
DISCORD_MAX_MESSAGES = 2  # 실행당 메시지 상한 → 최대 20건, 넘치면 "외 N건"
DISCORD_MESSAGE_DELAY = 1.0  # 초. 메시지 사이 간격
DISCORD_RETRY_AFTER_MAX = 10  # 초. 429(속도 제한)면 이만큼까지만 기다렸다가 한 번 더 시도한다
DISCORD_DEFAULT_COLOR = 0xEDC15A  # 멤버 색을 못 찾을 때(그룹·단체). 사이트 강조색(다크)
YOUTUBE_THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"  # 사이트와 같은 썸네일 (핫링크, 저장 안 함)

# --- 갱신 정체 감시 (watchdog.py, 기능 0-e) ------------------------------------------
# 배포된 사이트의 news.json updatedAt이 오래됐고 update.yml 실행이 정체돼 있으면 그 실행을 취소하고 디스코드에 경고한다.
# 2026-10-07: waiting 상태로 남은 실행 하나가 concurrency 그룹 `pages`를 잡아 사이트가 약 22.5시간 갱신되지 않았다 (PROGRESS 알려진 문제 3)
GITHUB_API_URL = "https://api.github.com"
GITHUB_DEFAULT_REPO = "sora7942/stella-radar"  # Actions에서는 환경변수 GITHUB_REPOSITORY가 우선한다
UPDATE_WORKFLOW_FILE = "update.yml"
WATCHDOG_WORKFLOW_FILE = "watchdog.yml"
WATCHDOG_STALE_MINUTES = 90  # updatedAt이 이보다 오래(넘게) 지났으면 정체. 30분 주기에서 세 번 연속 놓친 정도
WATCHDOG_RUN_MAX_AGE_MINUTES = 30  # update 실행이 이보다 오래(넘게) queued/waiting/in_progress면 정체된 실행 (정상 실행은 몇 분이고 timeout은 15분)
WATCHDOG_RUN_STATUSES = ("queued", "waiting", "in_progress")
WATCHDOG_REPEAT_HOURS = 6  # 같은 정체로는 처음 한 번, 이후 이 간격마다 한 번만 경고한다
WATCHDOG_REPEAT_GRACE_MINUTES = 10  # 1시간 간격 점검이 몇 분 늦거나 빨라도 6시간째 경고를 한 칸 건너뛰지 않게 하는 여유
WATCHDOG_ALERT_STEP = "경고 발송"  # watchdog.yml의 단계 이름. 이전 실행에서 이 단계가 success면 그때 경고를 보낸 것이다 (상태를 따로 저장하지 않는다)
WATCHDOG_RUNS_PER_PAGE = 30  # 이전 점검 실행을 훑는 개수 (1시간 간격 × 7시간 + 수동 실행 여유)
WATCHDOG_COLOR = 0xE5484D  # 경고 임베드 색
