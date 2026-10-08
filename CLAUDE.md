# stella-radar
스텔라이브 비공식 팬 허브. 정적 사이트(GitHub Pages) + 30분마다 도는 Python 업데이터(GitHub Actions — 외부 cron이 `workflow_dispatch`로 30분마다 호출).
요구사항, 데이터 스키마, 완료 기준은 @SPEC.md 참고.

## Stack
- 사이트: `site/index.html` 한 파일 (바닐라 HTML/CSS/JS, 빌드 없음) + `site/data/*.json`
- 업데이터: Python 3.12 (로컬 conda env: `stella`) — requests, feedparser, beautifulsoup4, python-dotenv, pytest
- 실행 환경: GitHub Actions (ubuntu-latest), 로컬은 Windows + PowerShell

## Commands
- 환경 만들기 (최초 1회): `conda create -n stella python=3.12 -y; conda activate stella; pip install -r requirements.txt`
- 이후 작업 전: `conda activate stella`
- 수집, 알림 없이: `python main.py --dry-run` (알림 파일을 남기지 않고 보낼 내용만 콘솔에 출력)
- 일부 소스만: `python main.py --dry-run --only youtube`
- 알림 발송(배포 성공 뒤 단계): `python send_alerts.py` — `out/alerts.json`만 읽는다. 로컬에서는 `--dry-run`으로 내용만 확인
- 사이트 미리보기: `python -m http.server -d site 8000` → http://localhost:8000
- 테스트: `pytest -q`

## Structure
- 사람이 고치는 데이터: `site/data/members.json`, `songs.json`, `events.json` — 업데이터는 읽기만 한다
- 자동 생성 데이터: `site/data/news.json`, `catalog.json`, `status.json` — 업데이터만 쓴다
- URL·주기·개수 제한·알림 규칙은 `updater/config.py` 한 곳에만 둔다
- 수집기는 `updater/sources/`에 소스별 파일로 두고, SPEC 4장 형식을 반환한다
- 테스트용 저장 응답은 `tests/fixtures/`
- 일회성 도구는 `tools/`에 둔다(예: `tools/find_song_videos.py`). 업데이터·`main.py`·`send_alerts.py`는 `tools/`를 import하지 않는다(`tests/test_find_song_videos.py`가 확인). `tools/`는 `updater`(http·config·redact)를 import해도 된다

## Rules
- 모든 외부 HTTP 요청에 `timeout=10`과 User-Agent 헤더를 넣는다
- 소스 하나가 실패해도 전체 실행은 계속한다. 실패한 소스는 로그에 남긴다
- 시간은 timezone-aware datetime, 저장은 `+09:00` ISO 문자열
- JSON은 `encoding="utf-8"`, `ensure_ascii=False`로 쓴다
- `news.json` 항목의 `added`는 처음 발견한 시각에서 절대 바꾸지 않는다
- `site/index.html`을 고칠 때는 SPEC 4장 스키마와 맞는지 확인하고, 데스크톱·모바일(400px) 폭, 라이트·다크 모드에서 확인한다

## Critical
- NEVER: 이미지(썸네일·프로필)를 내려받아 저장소에 넣지 않는다. 항상 원본 URL로 링크만 건다
- NEVER: 테스트에서 실제 네트워크·디스코드를 호출하지 않는다
- NEVER: 실제 디스코드 발송은 사용자가 요청할 때만 한다. 개발 중에는 `--dry-run`
- NEVER: `DISCORD_WEBHOOK_URL`을 코드·로그·커밋에 남기지 않는다 (`.env`는 `.gitignore`). requests 예외 메시지에는 URL이 들어 있으니 발송 실패는 예외 종류·HTTP 상태만 기록한다
- NEVER: `YOUTUBE_API_KEY`를 코드·로그·예외 메시지·커밋에 남기지 않는다. 키는 URL이 아니라 `X-Goog-Api-Key` 헤더로만 보내고, API 오류는 HTTP 상태와 reason 코드만 기록한다(예외 메시지·응답 본문 금지). `updater/redact.py`가 마지막 방어선이고 `tests/test_secrets_hygiene.py`가 저장소를 스캔한다
- NEVER: 외부 cron용 GitHub 토큰(`github_pat_…`)을 저장소·로그·문서·GitHub Secret·`.env`에 남기지 않는다. 값은 cron-job.org의 헤더 칸에만 있고 문서에는 `<토큰>`만 쓴다. `tests/test_secrets_hygiene.py`가 `github_pat_`·`ghp_`·`sk-ant-` 모양을 잡는다
- 새로 만든 비밀 파일·픽스처는 커밋 전에 `pytest -q tests/test_secrets_hygiene.py`로 확인한다 (커밋될 파일 전체와 로컬 `.env`의 실제 값을 대조한다)
- 웹훅 URL은 `send_alerts.py`만 읽는다. `main.py`는 디스코드로 보내지 않고 알림을 `out/alerts.json`(site/ 밖, `.gitignore`)에 남긴다
- stellive.me와 유튜브에 요청을 몰아 보내지 않는다 (음악 상세는 실행당 40개, 요청 간 0.5초)

## Gotchas
- 아티팩트 시절 데이터를 그대로 가져왔다: 노래 대표곡 `songs.json`의 `yt`는 대부분 null이고, 사이트가 catalog에서 제목으로 찾아 채운다
- 유튜브 영상은 YouTube Data API가 기본이고 RSS는 키가 없거나, 할당량이 초과됐거나, 키가 거부됐을 때만 쓴다(`updater/sources/youtube_api.py`, RSS 코드는 `youtube_rss.py`에 그대로). 키 거부는 Actions 주석 "YouTube API 키 확인 필요"로 알린다. 5xx·네트워크 같은 그 밖의 API 실패는 RSS로 돌리지 않는다. 하루 약 580유닛(한도 10,000)이며 `search.list`(호출당 100유닛)는 업데이터 코드에서 거부된다(`config.YOUTUBE_API_ENDPOINTS` 허용 목록). 예외는 일회성 `tools/find_song_videos.py`뿐이다(`--plan`으로 비용 확인, 호출 상한 21회 = 2,100유닛, `songs.json`은 쓰지 않음)
- 치지직 live-status는 비공식 API라 언제든 막힐 수 있다. 막히면 그 소스만 끄고 보고한다. v2가 5xx면 v3(`config.CHZZK_LIVE_STATUS_URLS`)로 대체하고, 같은 멤버가 연속 3회 실패하면 Actions 주석 경고가 나온다(`status.json` 멤버의 `liveFails`, SPEC 4장). 후야 방송이 Actions(해외 IP)에서 v2만 HTTP 500 `code 9004`("해외 시청 불가능한 컨텐츠")로 막혔고 v3는 통과했다(PROGRESS)
- 사이트는 치지직 `live.checkedAt`이 2시간 넘게 지난 LIVE를 숨긴다 (`site/index.html`의 `LIVE_MAX_AGE_MS`). 치지직 요청이 실패한 멤버는 이전 live 값이 그대로 남지만 checkedAt이 멈추므로, 소스를 끄거나 계속 실패해도 오래된 LIVE는 사라진다
- **정기 실행은 외부 cron(cron-job.org)이 30분마다 `workflow_dispatch`를 호출하는 것이 주 경로다**(SPEC 9장). GitHub `schedule`(`7,37`, UTC)은 이 저장소에서 한 번도 시작되지 않아 보조일 뿐이고(돌더라도 몇 분씩 늦거나 건너뛴다), 겹쳐 돌아도 `concurrency`와 '새 항목 없음 → 알림 없음'으로 안전하다. 외부 cron이 멈추거나 토큰이 만료되면 갱신이 멈추므로 사이트의 "마지막 관측" 시각으로 확인한다
- 배포된 사이트에서 이전 상태를 읽으므로(SPEC 6장), Pages 배포가 실패하면 다음 실행은 마지막 성공 배포 기준으로 다시 수집한다. 알림은 배포 성공 뒤 단계(`send_alerts.py`)에서만 나가므로 중복 알림은 없다. 대신 그 단계가 실패하면 그 알림은 다시 시도되지 않는다(최대 한 번)
- 유튜브 채널 이미지(yt3) 등 외부 이미지는 `referrerpolicy="no-referrer"`가 있어야 잘 뜬다 (index.html에 이미 들어 있음)
- Windows에서 `conda run`은 한글 출력을 깨뜨린다. `conda activate` 후 실행하거나 `conda run --no-capture-output`

## Compaction
- When compacting, always preserve the list of modified files, the current step in SPEC.md section 12, and test commands.
