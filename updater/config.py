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
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# --- 소식 피드 -----------------------------------------------------------------
NEWS_MAX_ITEMS = 300  # news.json 보관 상한 (date 내림차순)
