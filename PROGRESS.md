# PROGRESS — stella-radar

SPEC 12장 진행 상황. 새 세션은 이 파일 → `SPEC.md` → `CLAUDE.md` → 계획 파일(`~/.claude/plans/pasted-content-id-2971-spec-md-cozy-llama.md`) 순서로 읽는다.

## 현재 위치
**단계 4 완료(사용자 확인 반영 포함), 단계 5 시작 전.** 로컬 `main`이 `origin/main`보다 앞서 있고(push 안 함), `pytest -q` → 328 passed.
단계 5로 가기 전에 사용자 확인을 받는다. 확인받을 것은 아래 "단계 4 반영 결과"의 RSS 상태.

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
| 4+ | 강지 치지직 ID 반영, `official_img` 대체·`img.top` CSS 제거, `live.checkedAt`+사이트 2시간 규칙, 아바타 `=s240` 저장, RSS 실패 로그 테스트 | 이 문서와 같은 커밋 |

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
**5**(`discord.py` + 판정 테스트: 6시간/2일/음악 날짜 창/off→on, 20개 초과 "외 N건", 웹훅 URL 미노출. `--dry-run` 출력 검토, 실제 발송은 사용자가 요청할 때 1건만) → **6**(Actions + README, push 전 확인) → **7**(예약 실행 확인, 이전 Claude 예약 작업 끄기는 사용자가 앱에서).

단계 5에서 쓸 것: `main.py`의 `ctx.prev_status`(이전 live)와 새 `members_status`를 비교해 off→on을 판정한다. 이전 항목이 없으면 off로 간주.
**미결정(단계 5에서 정하고 확인받을 것)**: 이전 live가 `on:true`인데 `checkedAt`이 2시간 넘게 지난 경우(치지직 확인이 오래 실패한 뒤 복구)를 off로 볼지. off로 보면 진행 중인 방송에 대해 복구 직후 방송 시작 알림이 한 번 나가고, on으로 보면 그 사이에 방송이 끝나고 새로 시작했어도 알림이 안 나간다.

## 단계 6에서 결정할 것
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
