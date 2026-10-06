"""URL·주기·개수 제한·알림 규칙은 전부 여기에만 둔다 (CLAUDE.md)."""
import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"

# --- 사이트 / 이전 상태 -------------------------------------------------------
DEFAULT_SITE_URL = "https://sora7942.github.io/stella-radar/"
STATE_FILES = ("news", "catalog", "status")  # 업데이터가 쓰는 파일 (이전 상태를 배포본에서 읽는다)
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

CHZZK_LIVE_STATUS_URL = "https://api.chzzk.naver.com/polling/v2/channels/{channel_id}/live-status"  # 비공식 API
CHZZK_LIVE_PAGE_URL = "https://chzzk.naver.com/live/{channel_id}"
CHZZK_RETRY_5XX = 1  # HTTP 5xx면 이만큼 더 시도한다. 4xx·연결 오류·응답 형식 오류는 재시도하지 않는다
CHZZK_RETRY_DELAY = 1.0  # 초. 5xx 재시도 전 대기
CHZZK_FAIL_WARN_STREAK = 3  # 같은 멤버의 확인이 이 횟수(실행 단위)만큼 연속 실패하면 Actions ::warning:: 주석

# 기본으로 돌리는 소스. 치지직이 Actions(해외 IP)에서 막히면 여기서 "chzzk"만 뺀다 (CLAUDE.md). --only는 이 목록과 무관하게 지정한 것만 돌린다
ENABLED_SOURCES = ("youtube", "news", "music", "avatar", "chzzk")

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
