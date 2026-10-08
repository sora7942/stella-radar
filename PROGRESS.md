# PROGRESS — stella-radar

SPEC 12장 진행 상황. 새 세션은 이 파일 → `SPEC.md` → `CLAUDE.md` → 계획 파일(`~/.claude/plans/pasted-content-id-2971-spec-md-cozy-llama.md`) 순서로 읽는다.

## 현재 위치
**전 단계(0~7) 완료. 운영 중.** 사이트 https://sora7942.github.io/stella-radar/ 는 **외부 cron(cron-job.org)이 30분마다 `workflow_dispatch`를 호출**해 갱신된다(GitHub `schedule`은 이 저장소에서 한 번도 돌지 않아 보조로만 남김). 로컬 `main`과 `origin/main`은 이 문서 커밋까지 같다.
미해결 문제 2개(아래 "알려진 문제"): ① 치지직 후야 방송이 Actions에서 v2만 HTTP 500(원인 확인: 해외 시청 제한 code 9004, v3 대체를 로컬 커밋으로 구현 — Actions 반영 대기) ② GitHub `schedule` 미작동(원인 미확정, 외부 cron으로 우회).

## SPEC v1.1 진행 (기능 0 → 1 → 2 → 3)
계획 파일: `~/.claude/plans/pasted-content-id-2204-spec-v1-1-md-groovy-pudding.md`. 규칙: 기능마다 멈추고 검증 결과를 보여준 뒤 확인, 단계마다 로컬 커밋, **push는 매번 먼저 묻는다.** 새 세션은 이 파일 → `SPEC.md` → `SPEC-v1.1.md` → `CLAUDE.md` 순서로 읽는다.

| 단계 | 내용 | 상태 · 커밋 |
|---|---|---|
| 0-a | 비밀 스캔에 `github_pat_`/`ghp_`류/`sk-ant-` 패턴, `.env` 대조·conftest에 `ANTHROPIC_API_KEY` | 완료 `d64c1c4` (가짜 토큰으로 일부러 깨뜨려 2건 모두 잡힘 확인) |
| 0-b | SPEC 9장·CLAUDE.md·README의 cron 문구를 외부 cron 주 실행 구조로, SPEC-v1.1 굿즈 토글 문구 수정 | 완료 `f7e6300` |
| 0-c | 치지직 5xx 재시도 + 같은 멤버 연속 3회 실패 시 `::warning::`(`status.json` 멤버 `liveFails`) | 완료 `498ec7e`. 테스트 619→656개, 변형 7종을 모두 테스트가 잡음. 로컬 실요청 11명 정상 |
| 0-d | 치지직 대체 엔드포인트 시험(Actions IP, `probe/chzzk` 임시 브랜치) → **v2 우선, 5xx면 v3 대체 채택**(사용자 결정). "5xx 재시도"는 "다음 엔드포인트 → 전부 5xx면 한 바퀴 더"로 바뀜 | 완료 `98a8c46`(2026-10-08 확인: `main`은 `origin/main`과 같다 — 이미 push됨). 시험 run 37483326938. 테스트 656→670개, 변형 7종 모두 잡음. `probe/chzzk` 원격 브랜치는 정리 전 |
| 1 | 대표곡 10곡 유튜브 영상 후보 표 → 사용자가 고른 ID만 반영 | 진행 중: 도구 `tools/find_song_videos.py` + 테스트 20개 완료(로컬 커밋, 전체 690개 통과, 변종 8종을 테스트가 모두 잡음). `--plan` 확인: 1차 11호출 = 1,100유닛, 최악 21호출 = 2,100유닛. **실호출(검색)·후보 표·사용자 선택·`songs.json` 반영은 아직** |
| 2 | 쇼츠 판별((a)/(b) 비교표 후 선택) + 피드 분류 필터·쇼츠 UI | 예정 |
| 3 | 공지 본문 추출 확인 → Claude 일정 추출 → `auto_events.json` → 달력 | 예정 |

**0-d 시험 결과 (2026-10-07 Actions run 37483326938, 후야 방송 중, 후보 6개 × 헤더 2종 × 후야·유니·강지)**

| 엔드포인트 | 한국 IP | Actions 후야 | Actions 유니·강지 |
|---|---|---|---|
| E0 `polling/v2/live-status` (현행) | 200 | **500 · code 9004 해외 시청 불가** | 200 |
| E1 `polling/v3/live-status` | 200 | **200 (OPEN)** | 200 |
| E2 `service/v1/live-detail` | 500 (9004 "앱 업데이트 후에…") | 500 (같음) | 500 — 폐기된 엔드포인트 |
| E3 `service/v2/live-detail` | 200 | 500 · code 9004 | 200 |
| E4 `service/v3/live-detail` | 200 | 200 | 200 |
| E5 `service/v1/channel` (`openLive`만) | 200 | 200 | 200 |

`Origin`/`Referer` 헤더는 결과를 바꾸지 않았다. v3 live-status의 `content`는 v2와 키 51개가 같고(`channelId`·`status`·`openDate`·`closeDate`·`liveTitle` 값 동일) 같은 파서로 읽힌다 → 실제 v3 응답을 `tests/fixtures/chzzk_live_v3_close.json`으로 저장. 시험 스크립트와 워크플로는 `probe/chzzk` 브랜치(커밋 `097be44`)에만 있고 `main`에는 없다.

**확정된 결정 (v1.1)**: 일정 추가 알림은 출처 공지가 2일 이내일 때만 · Claude 호출만 `timeout=30`(CLAUDE.md Rules에 예외 명시) · 수동·자동 일정 중복은 같은 시작일끼리만 비교(같은 시작일 AND (같은 url 또는 제목 포함)) · index.html 테스트는 순수 로직 구역을 node로 실행 · **굿즈 일정 보기 토글은 달력뿐 아니라 다가오는 일정 패널·"다음:" 문구에도 적용**(소식 탭 패널 머리에도 같은 상태의 작은 토글).

## 완료한 단계
| 단계 | 내용 | 커밋 |
|---|---|---|
| 0 | 의존성 목록, 실제 응답 픽스처(`tests/fixtures/`) | `6552608` |
| 1 | 저장소 배치, 현재 시드 화면 확인 (리제 `official_img`를 존재하는 `lize2.png`로 교체) | `22d0ab4`, `a5e0c63` |
| 2 | 유튜브 RSS 수집·태깅·상태 병합 (`youtube_rss`, `tagging`, `state`, `main`) | `ffb1a79` |
| 2+ | 시부키 별명 `부키` 태깅 (한글 별명은 단어 시작에서만 매칭, 오탐 테스트 포함) | `322a729` |
| 3 | 공식 공지·음악 카탈로그 수집, 음악 분류 판정 (`stellive_news`, `stellive_music`) | `f8d2725` |
| 3+ | 카탈로그 286곡을 `site/data/catalog.json` 시드로 추가 / main 테스트가 시드에 의존하지 않게 빈 카탈로그에서 시작 | `4d4b822`, `1a04e68` |
| 4 | 아바타(`youtube_avatar`)·치지직(`chzzk`) 수집, `state.merge_status`, `config.ENABLED_SOURCES` | `2bdc233` |
| 4+ | 강지 치지직 ID 반영, `official_img` 대체·`img.top` CSS 제거, `live.checkedAt`+사이트 2시간 규칙, 아바타 `=s240` 저장, RSS 실패 로그 테스트 | `b57c67f` |
| 5 | 알림 판정(`alerts.py`, 방송 시작은 since 규칙)·임베드/발송/dry-run(`discord.py`)·`http.post_json`, main 연결 | `d4fda1f` |
| 5+ | 알림을 배포 성공 뒤로: main은 `out/alerts.json`만 남기고, `send_alerts.py`가 그 파일만 읽어 발송 | `915d814` |
| 5++ | 유튜브 영상을 YouTube Data API 기본으로(키 없음·할당량 초과일 때만 RSS), 업로드 재생목록 ID 캐시, 키 비노출 장치(`redact.py`)와 저장소 비밀 스캔 테스트 | `035576d` |
| 5+++ | 키 거부도 RSS로 대체 + Actions `::warning::`("YouTube API 키 확인 필요"), `search.list`는 코드에서 거부(허용 목록) | `d44fb5e` |
| 6a | `update.yml`·`keepalive.yml`·`README.md`·워크플로 구조 테스트(로컬 작성·검증만, 원격 미반영) | `f8c715c` |
| 6b | push(`22d0ab4..f8c715c`) → Pages 설정(Source=Actions) → 첫 수동 실행 성공, 알림 7건 발송 | (원격 작업, 커밋 없음) / 이 문서의 커밋 |
| 6c | cron `*/30`→`7,37`(정각·30분 회피) push 실행(20:14) → 성공, 중복 알림 없음 | `dab6624` |
| 7 | GitHub `schedule` 미작동 확인 → 사용자가 외부 cron(cron-job.org)으로 대체, 이전 Claude 예약 작업 끔. README·PROGRESS 정리 | 이 문서의 커밋 |

단계 3 검증 결과: 카탈로그 286곡(EP 7 · SINGLE 19 · COVER 252 · OTHERS 8)이 분류 탭 라벨과 일치. 연속 실행으로 40→…→286까지 채워졌고 경고·오류 0건. 정상 상태 재실행은 목록 요청 1회뿐. 브라우저(1280px·400px)에서 "공식 전체 (286)", 썸네일 60/60, 콘솔 에러 없음.

단계 4 검증 결과 (2026-10-06 실제 네트워크, `--dry-run --only avatar,chzzk --local-state`):
- 아바타 11명 성공·실패 0, 서로 다른 URL 11개, HEAD 응답 전부 `image/*`. 재실행 시 요청 0명(24시간 이내), `avatarCheckedAt` 불변.
- 치지직 10명 성공 (강지는 `chzzk_id` 없어 제외). 검증 시점에 방송 중인 멤버는 없었다.
- 브라우저(1280px·400px × 라이트·다크 = 8조합): 멤버 사진 11/11, 콘솔 에러·실패 요청·가로 넘침 없음. LIVE 바와 카드 칩은 합성 `status.json`(리제·타비 방송 중)으로 확인.
- 검증으로 바뀐 `news.json`·`status.json`은 `git restore`로 시드 상태로 되돌렸다.

**발견한 것 (코드에 반영됨)**
- 유튜브 채널 페이지의 `og:image` 메타는 `<head>`가 아니라 `</head>` 뒤(body 안)에 있다(2026-10-06 실측: `</head>` 710,566번째, `og:title` 764,769번째). 파서는 문서 전체의 `<meta>`를 훑는다. 픽스처 `youtube_channel_kangji.html`이 이 배치를 유지한다.
- 방송 상태 요청이 실패한 멤버는 결과에서 빼서 이전 `live` 값을 유지한다(꺼짐으로 쓰면 다음 성공 때 가짜 off→on 알림).

## 단계 4 반영 결과 (사용자 확인 후)
- **강지 `chzzk_id`**: `b5ed5db484d04faf4d150aedd362f34b`를 `chzzk_id`와 `links.chzzk`(`https://chzzk.naver.com/<id>`)에 넣었다. 이제 치지직 11명 모두 확인한다.
- **공식 이미지 (b)**: `index.html`에서 `official_img` 대체(`imgTag([s.avatar])`)와 `.mono-av img.top` CSS, `M`에 복사하던 `official_img`를 지웠다. 아바타가 없거나 로딩에 실패하면 색 이니셜 원이 보인다. `members.json`의 `official_img` 필드 자체는 남겨 뒀다(SPEC 4장 스키마, 지금은 사이트가 읽지 않음). 원인 메모: 아바타 `<img>` 상자가 `display:grid` 때문에 64×64가 아니라 64×147~268로 그려져 크롭 값이 의도대로 동작하지 않았다. (a)를 시도했지만 상자만 고쳐서는 얼굴이 안 보였고 멤버별 보정이 필요해 보였다.
- **`live.checkedAt`**: 치지직을 성공적으로 확인한 시각(꺼짐에도 붙음). 실패한 멤버는 이전 값과 이전 checkedAt이 남는다. 사이트 `liveOf()`는 checkedAt이 2시간(`LIVE_MAX_AGE_MS`) 넘게 지났거나 없거나 읽을 수 없으면 LIVE를 숨긴다. 브라우저에서 10분·100분 전은 표시, 140분·600분 전·없음·읽을 수 없음은 숨김을 확인했다. SPEC 4장 status 스키마에 반영함.
- **아바타 `=s240`**: `=s900-…` → `=s240-…`로 크기 파라미터만 바꿔 저장(`config.AVATAR_SIZE`). 같은 서버(`yt3.googleusercontent.com`), 11개 HEAD 모두 이미지 응답, 합계 313KB(원본 크기 1.63MB의 19%).
- **RSS 채널 단위 격리**: 이미 `youtube_rss.collect`가 채널마다 try/except로 격리하고 실패를 `log.warning("유튜브 채널 실패 — <채널>: <오류>")`로 남기고 있었다. 실패한 채널 이름이 로그에 남고 나머지 채널은 정상 처리되는 것을 확인하는 테스트를 추가했다(`test_collect_logs_each_failed_channel_by_name`, `test_failed_channel_is_logged_and_the_others_are_still_collected`).
- **유튜브 RSS는 아직 복구되지 않았다** (2026-10-06 14시 전후): 리제·강지·공식 모두 404/500, 실제 Chrome으로 열어도 같은 404라 이 PC의 요청 방식 문제가 아니다. 실제 `--only youtube` 실행은 12개 채널 실패를 각각 로그에 남기고 "모든 소스가 실패해 중단", exit 1, `news.json` 불변이었다. 복구되면 `--only youtube --local-state`로 실제 수집을 한 번 검증해야 한다.

## 단계 5 결과
**규칙 (사용자 확정, `tests/test_alerts.py`로 고정)**
- 방송 시작은 `live.since` 기준: 새 since가 이전에 저장된 since와 **다를 때만** 알림. 같은 since면 확인 공백이 얼마나 길었든(예: 3시간) 알리지 않는다. since가 지금으로부터 1시간(`ALERT_LIVE_MAX_AGE_HOURS`) **넘게** 지났으면 늦은 알림이라 알리지 않는다(정확히 1시간은 알림). since가 없거나 읽을 수 없으면 이전 규칙(꺼짐/이전 항목 없음 → 켜짐).
- 확인에 실패한 멤버는 새 status에도 이전 live가 그대로라서 알림이 나지 않는다. 치지직을 안 돌린 실행도 마찬가지.
- 영상 6시간 이내(경계 포함, 미래 날짜도 새로 보였으니 알림), 공지·새 곡은 달력 기준 2일 이내. 알 수 없는 id 접두사·읽을 수 없는 날짜는 알리지 않는다(날짜 오류는 경고 로그).
- 순서: 방송 → 공지 → 새 곡 → 영상(같은 종류는 최신순). 한 메시지 임베드 10개, 실행당 2메시지(20건), 넘으면 마지막 메시지 본문에 "외 N건 더 있어요 → 사이트 주소".
- 임베드: author = `<멤버 이름(들)> · <종류>`(공지는 공지/굿즈/이벤트), title+url 링크, color = 첫 멤버 색(그룹·단체는 기본색 `0xEDC15A`), 유튜브면 `thumbnail`(i.ytimg.com 핫링크), 시각이 있으면 timestamp. `allowed_mentions: {parse: []}`로 제목의 @멘션이 걸리지 않게 함. 썸네일을 큰 `image`로 바꾸고 싶으면 `discord.build_embed` 한 줄.
- `--dry-run`은 보낼 내용을 콘솔에 출력(웹훅 있어도 안 보냄), `--no-discord`는 조용히 건너뜀, `DISCORD_WEBHOOK_URL`이 없으면 건너뜀. 발송 실패·알림 단계의 어떤 오류도 경고만 남기고 실행·배포를 계속한다.
- **웹훅 URL 비노출**: requests 예외 메시지에는 URL이 들어 있어서 실패는 예외 종류·HTTP 상태만 기록한다. 429는 `retry_after`(10초 이내)만큼 기다렸다가 한 번 더. 테스트가 로그·출력에 URL이 새지 않음을 확인하며, 일부러 깨뜨려 이 테스트가 누수를 잡는 것도 확인했다.

**검증 (2026-10-06)**
- 실제 데이터 `python main.py --dry-run --local-state`: 새 공지 16건 중 알림은 1건(10/05 공지 `sl-14044`), 나머지 15건은 피드에는 들어가지만 2일을 넘어 알리지 않음. 유튜브는 전 채널 404/500이라 영상 없음. 방송 중인 멤버 없음.
- 실제 픽스처 + 가짜 시계 통합 장면(영상·공지·굿즈·새 곡·방송 시작 5건)의 dry-run 출력과 JSON을 검토했고, 25건이면 20건 + "외 5건"으로 나옴.
- 판정 규칙 4개와 웹훅 누수·멘션 차단·429 재시도 4개를 일부러 깨뜨려 테스트가 각각 잡는지 확인했다.
- 실제 디스코드 발송은 하지 않았다. 검증으로 바뀐 `news.json`·`status.json`·`catalog.json`은 `git restore`로 시드 상태로 되돌렸다.

## 알림 구조 (단계 5+, 사용자 확정)
- **알림은 배포가 성공한 뒤에만 나간다.** 이유: 배포가 실패했는데 알림만 나가면 다음 실행이 같은 항목을 다시 '처음 본 것'으로 판단해 중복 알림이 난다.
- `main.py`는 디스코드로 보내지 않고(`post` 인자·웹훅 읽기 모두 없앰) 보낼 웹훅 페이로드를 `config.ALERTS_FILE`(`out/alerts.json`)에 남긴다. 이 파일은 `site/` 밖이고 `.gitignore`(`out/`) 대상이라 배포에 올라가지 않으며 웹훅 URL도 들어 있지 않다. 내용: `{createdAt, alertCount, messages:[…]}`.
- `main.py`는 **매 실행 맨 처음에** 이전 알림 파일을 지운다(이전 실행·dry-run의 알림이 나중에 나가지 않게). `--dry-run`과 `--no-discord`는 파일을 남기지 않는다(`--dry-run`은 콘솔에 출력).
- `send_alerts.py`가 **그 파일만** 읽어 발송한다(`--dry-run`이면 출력만). 웹훅 URL(`DISCORD_WEBHOOK_URL`)은 이 스크립트만 읽는다. 항상 종료 코드 0(배포는 이미 끝남) — 웹훅 없음·발송 실패는 경고 로그와 Actions `::warning::` 주석으로 드러낸다(Secret 확인에 쓸 수 있음). 모양이 이상한 파일은 보내지 않고, 발송을 시도한 뒤에는 파일을 지워 **최대 한 번**만 나간다(발송 단계가 실패하면 그 알림은 다시 시도하지 않음).
- 워크플로(6단계): 같은 잡의 마지막 단계로 `python send_alerts.py`를 둔다(앞 단계가 모두 성공했을 때만 실행 = 기본 동작). Secret은 이 단계의 `env`에만 넣는다. 업데이터 단계에는 노출하지 않는다.
- 검증: 465개 테스트. 일부러 깨뜨려 보는 7가지(dry-run·no-discord가 파일을 남김, 시작 때 옛 파일 미삭제, 발송 뒤 미삭제, 파일 검증 제거, 웹훅 없을 때 파일 삭제, 실패를 종료 코드로 전달)를 테스트가 모두 잡았다. 실제 데이터로 `main.py` → `out/alerts.json`(389바이트, 웹훅 문자열 없음, `site/` 안에는 없음) → `send_alerts.py --dry-run`이 그 파일만 읽어 같은 내용을 보여 주는 것까지 확인했다. 로컬에서는 `send_alerts.py`를 `--dry-run`으로만 돌렸다.

## 유튜브 영상 수집: YouTube Data API 기본, RSS는 대체 (단계 5++, 사용자 결정)
**결정**: 영상 수집은 YouTube Data API가 기본이고, RSS는 ① 키가 없을 때 ② 할당량 초과 ③ **키 거부**(400 `badRequest`·401·403 `forbidden`·`accessNotConfigured`·`ipRefererBlocked`; 사용자가 나중에 추가)일 때만 쓴다. ②③이 중간에 일어나면 못 한 채널만 RSS로. ③은 Actions 실행 요약에 `::warning::`("YouTube API 키 확인 필요 (HTTP … )")를 남긴다(`updater/annotate.py`, 로컬은 로그 경고만). 5xx·네트워크·속도 제한(`rateLimitExceeded`) 같은 그 밖의 실패는 RSS로 돌리지 않고 채널별 실패로 남긴다. RSS 코드(`youtube_rss.py`)는 그대로 남겼다. **`search.list`는 확인용으로만 썼고 업데이터 코드에 없다** — 호출은 `channels.list`·`playlistItems.list`뿐이고, `config.YOUTUBE_API_ENDPOINTS` 허용 목록에 없는 엔드포인트는 요청 전에 거부된다(테스트로 고정, 코드 전체에 `"search"` 엔드포인트 문자열이 없음도 테스트).

**구현**: `updater/sources/youtube_api.py`
- `channels.list(part=contentDetails)`로 업로드 재생목록 ID를 구해 `status.json`에 캐시(멤버 key별 `uploads`, 공식 채널은 `official` 키). 캐시가 있으면 `channels.list`를 부르지 않고, 캐시된 ID가 `playlistNotFound`면 그 채널만 다시 구해 한 번 재시도한다.
- `playlistItems.list(part=snippet,contentDetails, maxResults=15)`로 채널당 최신 영상. 호출 12회 + (캐시가 없을 때) 1회 → 하루 약 580유닛(한도 10,000).
- 게시 시각은 `contentDetails.videoPublishedAt`. 삭제·비공개는 이 값이 없어 건너뛴다.
- **키는 `X-Goog-Api-Key` 헤더로만 보낸다.** 오류는 HTTP 상태와 reason 코드만 기록하고(`raise … from None`으로 원래 예외도 숨김) 예외 메시지·응답 본문은 쓰지 않는다. `updater/redact.py`(마지막 방어선: 등록된 비밀을 로그 출력 직전에 가림 + 소스 실패 로그에서도 가림), `tests/test_secrets_hygiene.py`(커밋될 파일 전체와 로컬 `.env`의 실제 값을 스캔).

**실제 응답으로 확인한 것 (2026-10-06, 12개 채널 × 15개 = 180개 영상)**
- `X-Goog-Api-Key` 헤더만으로 200. 키 없이 보내면 403 `forbidden`, 엉터리 키는 400 `badRequest`(둘 다 실제 응답을 픽스처로 저장). 403이어도 `forbidden`은 할당량 초과가 아니다.
- 업로드 재생목록 ID는 12개 모두 `UU`+채널 ID와 일치하고 전부 최신순. 삭제·비공개 항목은 0건.
- `contentDetails.videoPublishedAt`은 영상 자체의 게시 시각(`videos.list`의 `snippet.publishedAt`)과 **180/180 일치**. 이 표본에서는 `snippet.publishedAt`(재생목록 추가 시각)도 180/180 같아서 두 필드의 차이는 관찰하지 못했다(그래도 `videoPublishedAt`을 쓴다 — 사용자 지시, 더 안전).
- **쇼츠**: 재생목록 항목에 쇼츠 표시가 없다(`contentDetails`는 `videoId`·`videoPublishedAt`뿐). 일반 영상과 같은 모양으로 들어오며, 이 표본의 60초 이하 영상 42개가 그렇다. 걸러내지 않는다.
- **라이브 다시보기·프리미어**: 5개가 `liveStreamingDetails`를 가진 영상이었고 모두 지난 방송(`liveBroadcastContent: none`)이다. 재생목록에서는 일반 영상과 구별되지 않는다. 프리미어 커버곡은 `videoPublishedAt`이 예정 시각이 아니라 **실제 시작 시각**(예: 예정 08:30:00Z → 08:30:07Z)이다.
- **예정(upcoming) 프리미어/라이브는 실제 응답으로 보여주지 못했다**: `search.list`로 12개 채널의 예정·진행 중 이벤트를 확인했지만 지금은 전부 없었다. 예정 영상이 업로드 재생목록에 언제부터 나오는지(RSS는 예정 프리미어도 포함했다)는 **미확인**이다 — 실제로 예정 방송이 생겼을 때 확인할 것. (`search.list` 24회 = 2,400유닛을 썼다.)
- RSS와의 교차 검증(RSS가 17:48에 12/12로 복구된 직후): 같은 영상 180개에서 게시 시각 180/180·태그 180/180·출처 180/180 일치, 제목 179/180(채널이 제목을 수정한 영상 1개).
- 실제 실행: `--dry-run --only youtube --local-state` → API로 12개 채널·영상 180개, 2회차는 캐시를 써서 `channels.list` 없이 같은 결과, 키 없음(환경변수 비움)이면 RSS로 대체. 출력과 만들어진 파일에 키 없음.

**유튜브 RSS 상태**: 14:54에는 12개 채널 모두 404/500이었으나 17:48에 12/12 정상으로 돌아왔다(원인·지속 여부는 모름). 이제 API가 기본이므로 RSS는 대체 경로다.

## 확정된 결정 (계속 지킬 것)
**작업 방식**
- 단계(4~7)마다 멈춘다. 실행한 검증 명령과 출력을 보여주고 사용자 확인을 받은 뒤 다음 단계로 간다.
- 단계마다 로컬 커밋. **push 하지 않는다.**
- `git push`, Pages 설정, 디스코드 실제 발송은 반드시 먼저 묻는다. `DISCORD_WEBHOOK_URL` Secret은 사용자가 이미 등록했다.
- 작업 중 생성된 `site/data/{news,catalog,status}.json`은 커밋하지 않고 `git restore site/data`로 시드를 되돌린다.

**설계 (계획 파일 "확정된 결정")**
- 공지는 목록 최신 30건만 (`NEWS_LIST_LIMIT=30`).
- 음악 알림·피드는 날짜 창 규칙: catalog에 처음 들어온 곡 중 발매일이 디스코드 2일 / news 피드 14일 이내인 것만.
- 이전 상태 읽기는 **404만** 저장소 파일 fallback. 타임아웃·5xx·JSON 오류는 3회 재시도 후 실행 실패(배포 건너뜀). SPEC 6·10장에서 의도적으로 벗어난 부분.
- 60일 cron 중지 방지용 월 1회 keepalive 커밋은 `update.yml`과 분리한 `keepalive.yml`에서 한다 (단계 6, SPEC 9장에 없는 추가 파일).
- 음악 분류 탭은 끝 페이지까지 따라가고, 상한(`MUSIC_TAB_MAX_PAGES=30`)에 닿거나 탭 읽기가 실패하면 음악 소스 실패 처리(이전 catalog 유지). COVER 개수 불일치와 처음 보는 탭 이름은 경고 로그.

**데이터**
- 별명은 `shibuki: 부키` 유지.
- 대표곡 10곡의 `songs.json` `yt`는 지금 그대로 둔다. 사용자가 나중에 링크를 준다. 대상: `SYNC 100%`, `불꽃`, `슈퍼삐질게하는법`, `Ready to Fire!`, `DIVE 2 FIGHT`, `Colorful Tempo`, `꿈의 신호`, `도깨비꽃`, `Lulala! Lululala!`, `눈꽃`.
- `who`가 빈 카탈로그 곡 25곡은 모두 졸업 멤버 아이리 칸나 곡이며 SPEC대로 `[]`.
- 강지 `chzzk_id`는 `b5ed5db484d04faf4d150aedd362f34b` (사용자 확인 후 반영).

## 단계 6 결과 (2026-10-06)
**① push 후 자동 실행 (18:28, run 37443184257)**: 예상대로 `deploy-pages`에서 실패(`Failed to create deployment (status: 404) … Ensure GitHub Pages has been enabled`), 알림 단계는 건너뜀 → **알림 없음**(배포 실패 시 알림이 나가지 않는다는 설계를 실제로 확인). 수집 단계는 성공했다.
**② Pages 설정 (18:31)**: `gh api -X POST repos/sora7942/stella-radar/pages -f build_type=workflow` → `build_type: workflow`, https 강제, 주소 `https://sora7942.github.io/stella-radar/`.
**③ 첫 수동 실행 (18:32, run 37443684428, `workflow_dispatch`, no_alerts=false) — 성공 (약 70초)**
- 실행 직전 dry-run 목록: 7건(공지 1 · 영상 6), 기준(10건 이하, 영상 6시간·공지 2일 이내)을 알림 코드와 별개로 짠 검사 스크립트로 확인 → 이상 없음 → 사용자 사전 지시대로 확인 대기 없이 실행.
- 단계: checkout · setup-python · pip install · 수집 · upload-pages-artifact · deploy-pages · 알림 발송 모두 success. 경고·오류 주석 없음.
- 알림: 수집 단계 `알림 7건(메시지 1개)을 out/alerts.json에 남겼습니다`(방송 0 · 공지 1 · 새 곡 0 · 영상 6) → 발송 단계 `디스코드: 메시지 1개 발송, 0개 실패 (알림 7건)`. 실행 직전 목록과 같은 건수.
- Actions(해외 IP)에서 확인됨: YouTube API 12개 채널·영상 180개(키 거부·할당량 경고 없음), 아바타 11/11, 치지직 11명 응답(막히지 않음), stellive.me 공지·음악. 유튜브 RSS 대체는 쓰이지 않았다.
- 배포된 사이트: `/`·`data/{news,catalog,status,members}.json` 모두 200, **`out/alerts.json`·`data/alerts.json`·`alerts.json`은 404(알림 파일은 배포에 섞이지 않음)**. news 214항목(영상 180·공지 30), catalog 286곡, status 12키(아바타 전부 `=s240`, `uploads` 캐시 12개), 방송 중 yuni·mashiro(`checkedAt` 기록됨).
- 실제 브라우저로 배포 주소 확인(데스크톱 라이트·400px 다크): "마지막 관측 2분 전", 피드 40건, LIVE 바(유니·마시로)와 카드 LIVE 칩, 멤버 사진 11/11, 노래 탭 "공식 전체 286", 콘솔 에러 0건·실패 요청 0건·가로 넘침 없음. (썸네일은 화면 밖 이미지가 지연 로딩이라 일부만 로드된 상태로 셌다.)

## 7단계 결과 (2026-10-06)
**① GitHub `schedule`(예약 실행)이 돌지 않았다 (원인 미확정)**
- 워크플로 2개 `active`, Actions 허용, 기본 브랜치에 cron 존재, 저장소 비활성화·보관 아님, githubstatus.com "All Systems Operational"(Actions·Pages 정상). 설정 문제는 찾지 못했다. 공식 문서: schedule은 고부하(특히 매 정각 부근)에 지연되거나 큐의 작업이 버려질 수 있다.
- `*/30 * * * *`: 워크플로를 올린 18:28부터 20:14까지 약 106분(18:30·19:00·19:30·20:00 슬롯 4개) → 0건. `7,37 * * * *`(dab6624, 정각·30분 회피)로 바꾼 뒤 20:14~23:17(슬롯 20:37·21:07·21:37·22:07·22:37·23:07, 6개) → 0건. 23:17 기준 저장소의 모든 실행: `push` 2·`workflow_dispatch` 3·**`schedule` 0**. (21:04에 사용자가 대기를 중단시켜 21:07 슬롯 이후는 폴링하지 않고, 23:17에 실행 목록으로 확인했다.)
- **그래서 사용자가 외부 cron으로 대체했다 (사용자 보고, 직접 설정)**: cron-job.org가 `POST https://api.github.com/repos/sora7942/stella-radar/actions/workflows/update.yml/dispatches`, 본문 `{"ref":"main"}`, 헤더 Accept·Authorization(Bearer fine-grained PAT: 이 저장소 하나·Actions Read/Write만·만료 1년)·X-GitHub-Api-Version·Content-Type, 30분마다. 이전 Claude 예약 작업은 끔. **토큰 값은 어디에도 기록하지 않는다(cron-job.org에만).** 설정 방법은 README "외부 cron으로 30분마다 실행하기".
- 직접 확인한 것: 22:50:50(KST) 테스트 실행(run 37474048276)과 23:00:41 정기 실행(run 37475389223) 모두 `event=workflow_dispatch`, 전 단계 success. `update.yml`의 `schedule`(`7,37`)은 그대로 둔 보조 트리거(겹쳐 돌아도 `concurrency: pages`로 순서대로, 새 항목이 없으면 알림도 없음).

**② push 실행(20:14, run 37455049957, cron 변경 커밋) — 성공, 중복 알림 없음**
- 이전 상태를 **배포본에서 정상 로드**(404 폴백 로그 없음). 새 항목 **0건**, 알림 **0건**, 발송 단계 "보낼 알림이 없습니다". → **첫 실행의 7건(공지 1·영상 6)은 다시 나가지 않았다(재발송 0건).**
- 방송 3건(타비 18:59·나나 19:00·후야 19:07 시작)은 **1시간 규칙으로 제외**: push 시점 20:14에 이미 타비 75분·나나 74분·후야 67분이 지났다(기한 19:59·20:00·20:07 — 첫 수동 실행(18:32)과 이 실행(20:14) 사이에 정기 실행이 없어서 놓침). 이는 버그가 아니라 규칙대로의 동작이고, 실행이 오래 비면 방송 알림이 사라진다는 사실을 실제로 보여준다.
- 사이트 `updatedAt` 18:32:51 → 20:14:24 갱신 확인.
- 외부 cron 실행에서도 중복 없음: 22:50 실행은 방송 시작 알림 1건 발송(`메시지 1개 발송, 0개 실패`), 바로 다음 23:00 실행은 새 항목 0건·알림 0건 → **같은 방송을 다시 알리지 않았다.**

## 알려진 문제 (미해결)
1. **치지직 후야 채널이 Actions에서 계속 HTTP 500 — 원인 확인, 대체 구현은 로컬 커밋(Actions 반영 대기).** 20:14·22:51·23:01 실행 모두 `치지직 실패 — 사키하네 후야: HTTPError: 500`(나머지 10명은 정상). 같은 시각 이 PC에서는 `live-status` 200·`status: OPEN`이었다. 영향: 실패한 멤버는 이전 값이 유지되므로 배포된 `status.json`의 후야는 `{"on": false, "checkedAt": "18:32:51"}`에 멈춰 **후야의 LIVE 표시와 방송 시작 알림이 누락**된다(다른 멤버는 정상). **원인(2026-10-07 `probe/chzzk` Actions 시험)**: 응답이 `HTTP 500 · code 9004 "해외 시청 불가능한 컨텐츠 입니다."` — 후야의 방송이 해외 시청 제한이라 **v2 live-status가 해외 IP에서 의도적으로 막는 것**이다(일시 오류가 아님 → 같은 엔드포인트 재시도는 소용없다). 같은 해외 IP에서 `polling/v3`·`service/v3/live-detail`은 200이었다. **조치(v1.1 기능 0-c·0-d, 로컬 커밋)**: v2가 5xx면 v3로 대체(`config.CHZZK_LIVE_STATUS_URLS`), 둘 다 5xx면 1초 뒤 한 바퀴 더, 같은 멤버 연속 3회 실패 시 Actions 주석 경고(`liveFails`). **남은 것: 이 코드를 push해 Actions에서 후야가 실제로 v3로 읽히는지 로그("다음 엔드포인트 시도")로 확인.** 방송 단위 제한이라 다른 멤버도 해외 제한 방송을 켜면 같은 일이 생긴다(v3 대체가 그 경우도 덮는다). 아직 모르는 것: v3도 같은 방식으로 막히는 방송이 있는지.
2. **GitHub `schedule` 미작동**(위 7단계 ①). 외부 cron으로 우회 중. 외부 cron이 멈추면(서비스 장애·토큰 만료) 사이트 갱신이 멈춘다.

## 운영 메모
- 외부 cron 토큰(fine-grained PAT)은 **만료 1년**(정확한 만료일은 기록하지 않았다 — 사용자가 발급일 기준으로 달력에 적어 두기). 만료 전에 새 토큰을 발급해 cron-job.org 헤더를 바꾼다. cron-job.org의 실패 알림 설정을 권한다.
- 방송 시작 알림은 시작 1시간 안에만 나간다. 실행이 1시간 넘게 비면 그 사이 시작한 방송 알림은 사라진다.
- `keepalive.yml`은 GitHub `schedule`을 위한 보조(다음 달 1일에 처음 돈다). 외부 cron은 `workflow_dispatch`라 이 규칙과 별개일 수 있으나 이 저장소에서 확인하지는 않았다.
- 문서에는 토큰 값을 쓰지 않는다. 저장소의 비밀 스캔 테스트(`tests/test_secrets_hygiene.py`)는 Google API 키·웹훅에 더해 GitHub 토큰(`github_pat_…`, `ghp_…`)과 Anthropic 키(`sk-ant-…`) 모양도 검사한다(SPEC v1.1 기능 0-a에서 추가, 커밋 `d64c1c4`).

## 단계 6에서 결정할 것
- ~~배포 실패 시 중복 알림~~ 해결됨: 알림을 배포 성공 뒤 단계(`send_alerts.py`)로 옮겼다(위 "알림 구조").
- ~~첫 실제 실행 때 알림이 나간다(의도됨)~~ 완료(위 결과): **첫 실제 실행 때 알림이 나간다(의도됨)**: 배포본이 없으면 시드를 이전 상태로 보므로, 2일 이내 공지(예: `sl-14044`)·6시간 이내 영상 등이 첫 수동 실행의 마지막 단계에서 실제로 발송된다. 사용자가 이것을 Secret 확인을 겸한 테스트로 쓰기로 했다. 실행 전에 `--dry-run` 출력으로 무엇이 나갈지 알려 준다.
- ~~카탈로그 시드~~ 결정됨: 채워진 286곡을 `site/data/catalog.json` 시드로 커밋했다(첫 배포부터 "공식 전체"가 차 있음). `news.json`·`status.json`은 시드 상태 그대로 둔다. 이후 `git restore site/data`를 쓰면 `catalog.json`은 이 286곡 시드로 돌아간다.
- 치지직이 Actions(해외 IP)에서 막히는지는 첫 수동 실행 로그로 실측한다. 막히면 `config.ENABLED_SOURCES`에서 `"chzzk"`만 빼고 보고한다. 소스를 꺼도 배포본의 마지막 `live` 값은 남지만 `checkedAt`이 멈추므로 사이트가 2시간 뒤 LIVE를 숨긴다(단계 4+에서 해결).
- 유튜브 채널 페이지(`og:image`)가 Actions(해외 IP)에서도 같은 구조로 오는지는 첫 수동 실행 로그로 실측한다(동의 페이지 등이면 `AVATAR_HOSTS` 검사가 실패로 처리하고 이전 값을 유지한다).
- 유튜브 RSS가 복구됐는지, Actions(해외 IP)에서도 되는지는 첫 수동 실행 로그로 실측한다.

## 알려진 한계
- 한 곡의 상세 읽기가 계속 실패하면 매 실행의 40곡 슬롯을 한 칸씩 차지한다(실패 횟수 저장은 catalog 스키마 확장이 필요해서 넣지 않음). 지금까지 실패 0건.
- kind 규칙은 SPEC 문구 그대로라 현재 멤버 1명이면 외부 아티스트 협업도 `솔로`. 현재 데이터의 외부 협업 2건은 모두 커버라 영향 없음.

## 명령
- 환경: `conda activate stella`
- 테스트: `pytest -q`
- 수집(알림 없이): `python main.py --dry-run --only <소스> --local-state`
- 미리보기: `python -m http.server -d site 8000` → http://localhost:8000
