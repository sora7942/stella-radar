# PROGRESS — stella-radar

SPEC 12장 진행 상황. 새 세션은 이 파일 → `SPEC.md` → `CLAUDE.md` → 계획 파일(`~/.claude/plans/pasted-content-id-2971-spec-md-cozy-llama.md`) 순서로 읽는다.

## 현재 위치
**단계 5 완료(알림을 배포 성공 뒤로 옮기는 구조 변경 반영). 단계 6 시작 전 — 유튜브 RSS가 12개 채널 모두 실패 중이라 사용자 결정 대기.** 로컬 `main`이 `origin/main`보다 앞서 있고(push 안 함), `pytest -q` → 465 passed.
사용자 지시: RSS가 여전히 안 되면 6단계 진행 전에 결과를 보여주고 멈춘다 → 아래 "RSS 상태와 API 대체 검토". 실제 디스코드 발송은 한 번도 하지 않았다. 로컬 테스트 발송도 하지 않는다 — **6단계 Actions 첫 수동 실행에서 나가는 알림이 테스트(Secret 확인 겸)**.

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
| 5+ | 알림을 배포 성공 뒤로: main은 `out/alerts.json`만 남기고, `send_alerts.py`가 그 파일만 읽어 발송 | 이 문서와 같은 커밋 |

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

## RSS 상태와 API 대체 검토 (2026-10-06 14:54, 사용자 지시로 6단계 전에 확인)
- **12개 채널 모두 실패**: 404 11개, 500 1개(나나). 오후 내내(13시 전후부터) 같은 상태. 실제 Chrome으로 열어도 같은 404라서 우리 코드·요청 방식 문제가 아니다.
- 알려진 사실(검색 결과, 2차 자료): YouTube 피드 서버가 몇 시간씩 모든 피드에 404를 내는 일이 있었고, 2025-12부터 간헐적 404가 있었으며, **데이터센터 IP(Vercel·AWS)의 서버 요청에는 채널 상태와 무관하게 404/500을 내는 사례**가 보고돼 있다. → 지금 장애가 일시적이어도, Actions(데이터센터 IP)에서는 RSS가 구조적으로 불안정할 수 있다. 6단계 첫 수동 실행의 로그로 실측해야 한다.
- **YouTube Data API v3 대체안** (공식 문서 확인분): 기본 할당량 하루 10,000 유닛, `playlistItems.list`·`channels.list`는 호출당 1유닛(`search.list`는 별도 하루 100회 한도라 쓰지 않는다). `playlistItems.list`는 `maxResults` 최대 50. 채널의 업로드 재생목록은 `channels.list`의 `contentDetails.relatedPlaylists.uploads`로 얻는다. 12채널 × 30분 주기(하루 48회) = 576유닛/일 → 한도의 약 6%. 개발 시 확인할 것(문서 요약에서 확정하지 못함): 게시 시각 필드(`snippet.publishedAt` vs `contentDetails.videoPublishedAt`), 쇼츠·예정 프리미어·라이브 다시보기가 업로드 재생목록에 어떻게 나오는지, API 키를 헤더(`x-goog-api-key`)로 보낼 수 있는지.
- 설계 메모: ① API 키는 Secret(`YOUTUBE_API_KEY`)이고 URL 쿼리에 넣으면 requests 예외 메시지에 키가 들어가므로(웹훅 URL과 같은 문제) 헤더로 보내거나 예외 메시지를 남기지 않아야 한다. ② 키는 Google Cloud 프로젝트 생성·API 활성화가 필요하고 사용자 작업이다(공개 저장소라 Secret 외 노출 금지, 키는 YouTube Data API v3로만 제한). ③ 업로드 재생목록 ID는 채널 ID의 `UC`를 `UU`로 바꾼 것이라고 알려져 있으나 문서에서 확인하지 못했으니 `channels.list`로 한 번 받아 `members.json`에 넣는 편이 안전하다. ④ 구현은 `youtube_rss.py`와 같은 반환 형식(news 항목)을 내는 `youtube_api.py`를 두고 RSS는 폴백으로 남기는 방식이 자연스럽다. 이번에는 구현하지 않았다.

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

## 다음 할 일
단계 5 확인 후 → **6**(Actions + README, push 전 확인) → **7**(예약 실행 확인, 이전 Claude 예약 작업 끄기는 사용자가 앱에서).

**6단계 직전 확인 결과(사용자 지시)**: RSS는 14:54에도 0/12 → 사용자에게 결과를 보여주고 멈췄다. 사용자 결정(① RSS 복구를 기다림/② 6단계를 RSS 없이 진행하고 Actions에서 실측/③ API 대체 구현)을 받은 뒤 진행한다. 위 "RSS 상태와 API 대체 검토" 참고.

## 단계 6에서 결정할 것
- ~~배포 실패 시 중복 알림~~ 해결됨: 알림을 배포 성공 뒤 단계(`send_alerts.py`)로 옮겼다(위 "알림 구조").
- **첫 실제 실행 때 알림이 나간다(의도됨)**: 배포본이 없으면 시드를 이전 상태로 보므로, 2일 이내 공지(예: `sl-14044`)·6시간 이내 영상 등이 첫 수동 실행의 마지막 단계에서 실제로 발송된다. 사용자가 이것을 Secret 확인을 겸한 테스트로 쓰기로 했다. 실행 전에 `--dry-run` 출력으로 무엇이 나갈지 알려 준다.
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
