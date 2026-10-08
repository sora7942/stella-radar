# SPEC — stella-radar

스텔라이브(강지 · 1기 에버리스 · 2기 유니버스 · 3기 클리셰 · 단체 · 멤버 개인)의 새 소식, 노래, 팬 게임, 생일·일정을 한곳에서 보는 **비공식 팬 허브 사이트**.
GitHub Pages(공개 저장소)로 서비스하고, GitHub Actions가 30분마다(외부 cron 서비스가 호출한다 — 9장) 새 소식을 모아 사이트를 다시 배포하며, 새 소식은 디스코드 웹훅으로 알린다.

> 이전 버전은 Claude 아티팩트였다. 아티팩트는 외부 이미지를 못 불러오고 유튜브 RSS를 못 읽어서 옮긴다.
> 프론트엔드(`site/index.html`)는 이미 완성되어 있다. 이 SPEC의 주된 구현 대상은 **업데이터와 배포 워크플로**다.

## 1. 목표
- `https://sora7942.github.io/stella-radar/`에서 사이트가 열린다
- 멤버 프로필 사진(유튜브 채널 이미지)과 노래·영상 썸네일(유튜브)이 **링크(핫링크)로** 보인다. 이미지를 저장소에 복사하지 않는다
- 30분마다(외부 cron이 호출하며 GitHub·네트워크 사정으로 몇 분씩 밀릴 수 있음) 다음을 반영한다
  - 멤버 12개 유튜브 채널(강지·멤버 10명·공식)의 새 영상
  - 공식 홈페이지 공지(stellive.me/news)
  - 공식 음악 카탈로그(stellive.me/music) 새 곡
  - 치지직 방송 중 여부(LIVE 표시)
- 새 영상·새 공지·방송 시작은 디스코드로 알림이 온다
- PC를 꺼도 동작한다. 비용 0원 (공개 저장소 Actions 무료, LLM 호출 없음)

## 2. 범위 밖 (v1에서 하지 않음)
- 뉴스 기사 수집(웹 검색) — LLM 없이 품질 관리가 어려움
- X(트위터) 게시물 수집 — 공식 API 유료
- 일정(events) 자동 추출 — `events.json`은 사람이 직접 고친다
- 로그인, 댓글, 사용자별 설정
- 이미지 다운로드·재호스팅

## 3. 저장소 구조
```
stella-radar/
├─ .github/workflows/update.yml   # 수집 → 배포 → (배포 성공 뒤) 알림. 외부 cron이 30분마다 workflow_dispatch로 호출 (+ main push, 수동 실행, 보조 schedule)
│  ├─ keepalive.yml               # 한 달에 한 번 빈 커밋 (60일 비활동으로 GitHub 예약 실행이 꺼지는 것 방지 — 보조 장치)
│  └─ watchdog.yml                # 갱신 정체 감시: 외부 cron이 1시간마다 workflow_dispatch로 호출 (9장)
├─ site/                          # 그대로 Pages에 올라가는 정적 사이트
│  ├─ index.html                  # 완성본. 데이터 스키마(4장)만 맞추면 됨
│  └─ data/
│     ├─ members.json             # [사람] 멤버·그룹·링크·채널 ID (업데이터는 읽기만)
│     ├─ songs.json               # [사람] 대표곡 큐레이션
│     ├─ events.json              # [사람] 팝업·콘서트 등 일정
│     ├─ news.json                # [자동] 소식 피드
│     ├─ catalog.json             # [자동] 공식 음악 전체 목록
│     └─ status.json              # [자동] 아바타 URL, 방송 상태
├─ updater/
│  ├─ config.py                   # URL, 주기, 개수 제한, 알림 규칙
│  ├─ tagging.py                  # 제목·아티스트 → who 태그
│  ├─ sources/
│  │  ├─ youtube_rss.py
│  │  ├─ stellive_news.py
│  │  ├─ stellive_music.py
│  │  ├─ chzzk.py
│  │  └─ youtube_avatar.py
│  ├─ state.py                    # 이전 상태 불러오기, 병합·중복 제거·자르기
│  ├─ shorts.py                   # 쇼츠 판별: 채널의 UUSH/UULF 재생목록으로 news 항목의 short 채우기 (5장)
│  ├─ alerts.py                   # 알림 대상 판정 (순수 함수, 7장)
│  └─ discord.py                  # 임베드 생성·발송·dry-run 출력
├─ tests/ (fixtures/ 포함)
├─ main.py                        # 수집 → site/data 갱신 → out/alerts.json (보낼 알림)
├─ send_alerts.py                 # 배포 성공 뒤 out/alerts.json만 읽어 디스코드로 발송 (watchdog.yml도 같은 파일 형식으로 재사용)
├─ watchdog.py                    # 갱신 정체 점검: 오래된 update 실행 취소 + 경고를 out/alerts.json에 남김 (판정 로직은 updater/watchdog.py)
├─ requirements.txt
├─ .env.example
├─ CLAUDE.md
├─ SPEC.md
└─ README.md
```

## 4. 데이터 스키마 (프론트엔드가 기대하는 형식 — 바꾸면 index.html도 같이 고쳐야 함)

### members.json (사람이 관리)
```json
{"groups":[{"key":"everys","label":"에버리스","full":"1기생 에버리스","en":"EVERYS","note":"..."}],
 "official":{"yt_id":"UC...","links":{"site":"...","youtube":"...","x":"...","cafe":"...","shop":"...","graduation":"..."}},
 "members":{"lize":{"n":"아카네 리제","en":"Akane Lize","c":"#C8352E","g":"universe","bd":"10-01","debut":null,"fan":"피엔나",
   "art":"#Lize_art","clip":"#Lize_live","yt_id":"UC7-m6jQLinZQWIbwm9W-1iw","chzzk_id":"4325...","official_img":"https://stellive.me/files/attach/images/lize/lize.png",
   "links":{"profile":"...","youtube":"...","chzzk":"...","x":"..."}}}}
```
- 멤버 key: `kangji, yuni, huya, hina, mashiro, lize, tabi, shibuki, rin, nana, riko`
- 그룹 key: `boss(강지), everys, universe, cliche`
- 강지 `chzzk_id`는 채널 API(이름·인증 마크)와 live-status의 `channelId`로 교차 검증해 사용자 확인 후 채웠다

### news.json (자동)
```json
{"updatedAt":"2026-10-06T09:30:00+09:00",
 "items":[{"id":"yt-<videoId>","date":"2026-10-06T09:12:00+09:00","added":"2026-10-06T09:30:00+09:00",
   "cat":"영상","who":["lize"],"title":"...","url":"https://www.youtube.com/watch?v=<id>","source":"아카네 리제 유튜브","yt":"<videoId>"}]}
```
- `id` 규칙: 유튜브 `yt-<videoId>`, 공식 공지 `sl-<번호>`, 음악 `mu-<번호>`
- `cat`: `영상 | 공지 | 굿즈 | 이벤트 | 음악 | 방송` (공식 공지는 사이트의 카테고리 GOODS→굿즈, EVENT→이벤트, 그 외→공지)
- `date`: 원본 게시 시각(+09:00 ISO). 날짜만 알면 `YYYY-MM-DD`
- `added`: 업데이터가 처음 발견한 시각 — 사이트의 NEW 표시와 디스코드 알림 판정에 쓴다. **한 번 정해지면 바꾸지 않는다**
- `yt`: 유튜브 영상이면 videoId (사이트가 `i.ytimg.com/vi/<id>/mqdefault.jpg` 썸네일을 건다)
- `short`(bool, 선택, `yt-` 영상만): 쇼츠인가. **필드가 없으면 아직 판별 전(미정)이다** — 사이트는 일반 영상으로 취급한다. `true`는 채널의 쇼츠 탭 재생목록(UUSH…)에서 확인된 영상, `false`는 동영상 탭 재생목록(UULF…)에서 확인됐거나 처음 발견(`added`) 24시간 뒤에도 둘 다에 없는 영상(라이브 다시보기·예약 영상 등). **한 번 정해지면 바꾸지 않는다** (판별 규칙은 5장 '쇼츠 판별')
- 사이트(`index.html`)의 `short` 사용(기능 2-2): `short:true` 항목에 '쇼츠' 배지를 달고 제목·썸네일 링크를 `https://www.youtube.com/shorts/<id>`로 건다(`url` 필드는 그대로 watch 주소). 썸네일(`mqdefault.jpg`)은 가운데에 세로 화면이 있고 양옆이 흐린 320×180 이미지라서, 쇼츠는 9:16 칸(`object-fit:cover`)에 가운데만 보여 준다. 소식 탭에는 분류 칩(전체·영상·공지/이벤트·굿즈·음악, 그룹 칩 위, 그룹·멤버 필터와 AND)과 '쇼츠 숨기기' 토글(`localStorage` 키 `sr_hideShorts`, 기본 '보이기', 저장이 막혀도 동작)이 있다. `short`가 없는(미정) 항목은 일반 영상으로 보인다
- `who` 태그: 멤버 key / 그룹 key(`everys, universe, cliche`) / `all`(단체). 정렬 순서 무관
- 보관: `date` 내림차순 **최대 300개**
- 기존 저장소의 news.json에 들어 있는 공식 공지 18개는 시드로 유지한다

### catalog.json (자동)
```json
{"updatedAt":"...","items":[{"id":"12876","title":"악당주의보『STELLIVE Cliché 1st EP 「Colorful Strokes」』","artist":"Yuzuha Riko",
  "who":["riko"],"category":"EP","kind":"솔로","date":"2026-07-24","yt":"P_oxx3_VpIY","url":"https://stellive.me/music/12876"}]}
```
- `category`: 공식 사이트 분류 그대로 (`ALBUM | EP | SINGLE | COVER | OTHERS`)
- `kind` 변환: COVER→`커버`, OTHERS→`콜라보·OST`, 나머지는 아티스트로 판단 — STELLIVE→`단체`, 유닛명(Everys/Universe/Cliché)이나 멤버 2명 이상→`유닛`, 멤버 1명→`솔로`
- `who`: 아티스트 영문명 → 멤버 key (`Akane Lize`→`lize` …), 유닛명→그룹 key, STELLIVE→`all`, 졸업 멤버(Airi Kanna 등)→`[]`
- `yt`: 상세 페이지의 `youtube.com/embed/<id>` 에서 추출 (쿼리스트링 제거)

### status.json (자동)
```json
{"updatedAt":"...","members":{"lize":{"avatar":"https://yt3.googleusercontent.com/...","avatarCheckedAt":"...",
  "live":{"on":true,"title":"방송 제목","url":"https://chzzk.naver.com/live/<chzzk_id>","since":"...","checkedAt":"..."}}}}
```
- `uploads`: 유튜브 업로드 재생목록 ID 캐시(YouTube API 수집용, 멤버 key별 + 공식 채널은 `official` 키). 캐시된 ID가 `playlistNotFound`면 그 채널만 다시 구한다
- `avatar`: 유튜브 채널 페이지의 `og:image`. 크기 파라미터만 `=s900` → `=s240`으로 바꿔 저장한다(같은 서버·같은 이미지, `config.AVATAR_SIZE`). 하루 1번 갱신, 실패하면 이전 값 유지
- `live`: 치지직 방송 상태. 꺼져 있으면 `{"on":false,"checkedAt":"..."}`
- `liveFails`(선택, 정수): 치지직 확인이 **연속으로 실패한 실행 수**. 실패한 실행마다 +1, 성공하면 필드를 지운다(0은 저장하지 않는다). 실패한 멤버의 패치에는 `live`가 없어 이전 `live`·`checkedAt`이 그대로 남는다. `CHZZK_FAIL_WARN_STREAK`(3) 이상이면 Actions 실행 요약에 `::warning::`("<멤버>: 치지직 확인이 N회 연속 실패했습니다 (HTTP 500) …")을 매 실행 남긴다. 사이트·알림 판정은 읽지 않는다
- `live.checkedAt`: 치지직을 마지막으로 **성공적으로 확인한** 시각. 요청이 실패한 멤버는 이전 live 값과 이전 checkedAt이 그대로 남는다. 사이트는 checkedAt이 2시간 넘게 지났거나 없는 LIVE는 표시하지 않는다(소스를 끄거나 계속 실패해도 오래된 LIVE가 남지 않게)

### songs.json / events.json (사람이 관리)
- songs: `{"items":[{"date","title","who","kind","note","tracks"?, "yt": null|"<videoId>"}]}` — `yt`가 null이면 사이트가 catalog에서 같은 제목을 찾아 채움
- events: `{"items":[{"id","start","end"?,"title","who","note","url"}]}`

## 5. 수집 소스
| 소스 | 방법 | 비고 |
|---|---|---|
| 유튜브 새 영상 | **YouTube Data API v3가 기본**: `channels.list(part=contentDetails)`로 채널의 업로드 재생목록 ID를 구해 status.json에 캐시하고(멤버 key별 `uploads`, 공식 채널은 `official`), `playlistItems.list(part=snippet,contentDetails, maxResults=15)`로 채널당 최신 15개 (12개 채널 = 호출 12회 + 캐시가 없을 때 1회, 하루 약 580유닛 / 한도 10,000). RSS(`https://www.youtube.com/feeds/videos.xml?channel_id=<UC…>`)로 대체하는 경우는 셋뿐: ① 키(`YOUTUBE_API_KEY`)가 없을 때, ② 할당량 초과(403 `quotaExceeded`), ③ **키 거부**(400 `badRequest`·401·403 `forbidden`·`accessNotConfigured`·`ipRefererBlocked` 등). ②③이 중간에 일어나면 못 한 채널만 RSS로 수집한다. ③은 사람이 고쳐야 하므로 Actions 실행 요약에 `::warning::` 주석 "YouTube API 키 확인 필요"를 남긴다(로컬은 로그 경고). 5xx·네트워크 오류·속도 제한 같은 그 밖의 API 실패는 RSS로 돌리지 않고 해당 채널의 실패로 남긴다. 업데이터가 부르는 API는 `channels.list`·`playlistItems.list`(호출당 1유닛)뿐이며 `search.list`(호출당 100유닛)는 코드에서 거부된다(`config.YOUTUBE_API_ENDPOINTS`) | 게시 시각은 `contentDetails.videoPublishedAt`(영상 자체의 게시 시각). 쇼츠·라이브 다시보기·프리미어 커버는 응답에서 일반 영상과 구별되지 않아 그대로 포함(쇼츠 여부는 아래 '쇼츠 판별'이 따로 정한다). 공식 채널 영상은 제목에서 멤버 이름을 찾아 태그, 없으면 `all`. **키는 URL이 아니라 `X-Goog-Api-Key` 헤더로만 보낸다**(로그·예외 메시지에 남지 않게) |
| 공식 공지 | `https://stellive.me/news` 목록 HTML | Rhymix 기반. 제목·날짜·카테고리·`/news/<번호>` 파싱. 첫 페이지만 |
| 공식 음악 | `https://stellive.me/music` 목록 + `/music/<번호>` 상세 | 상세는 **처음 보는 번호만** 가져온다(실행당 최대 40개, 요청 간 0.5초). 최초 실행 때 전체(약 290곡)를 여러 번에 나눠 채움. 새 곡은 news에도 `음악`으로 추가 |
| 치지직 방송 | `https://api.chzzk.naver.com/polling/v2/channels/<id>/live-status`, HTTP 5xx면 `…/polling/v3/…/live-status`로 대체 (`config.CHZZK_LIVE_STATUS_URLS`) | **비공식 API**. `content.status == "OPEN"`, `content.liveTitle`. v2는 해외 IP에서 방송 단위로 막힐 수 있다(후야 방송: HTTP 500 `code 9004` "해외 시청 불가능한 컨텐츠 입니다.", v3는 200 — 2026-10-07 Actions 시험). v3의 `content`는 v2와 키 51개가 같아 같은 파서를 쓴다. 두 후보가 전부 5xx면 1초 뒤 후보 전체를 1회 더 돈다. 4xx·연결 오류·형식 오류는 대체·재시도하지 않는다. 같은 멤버가 연속 3회 실패하면 `::warning::`(4장 `liveFails`). 전부 실패하면 소스 실패로 세되 연속 실패 횟수는 저장한다. Actions(해외 IP)에서 막히면 이 소스만 끄고 사용자에게 보고 |
| 유튜브 프로필 | `https://www.youtube.com/channel/<UC…>` HTML의 `og:image` | 하루 1번 |

- **쇼츠 판별**(`updater/shorts.py`, news 항목의 `short`, 기능 2-1): 유튜브가 직접 분류한 채널 재생목록으로 정한다 — 채널 ID의 `UC`를 `UUSH`로 바꾸면 쇼츠 탭, `UULF`로 바꾸면 동영상 탭(`playlistItems.list`, 호출당 1유닛. 비공식 관례지만 2026-10-09 실측에서 12채널 모두 열렸고 UUSH 87 + UULF 222 = 전체 업로드 309개로 누락·초과·겹침이 없었다)
  - 대상: `short` 필드가 없는 `yt-` 항목(`mu-` 음악은 채널을 알 수 없어 제외). 병합 뒤·저장 앞 단계라서 병합 밖의 기존 항목 백필과 '미정 항목 재시도'가 된다
  - 그 영상의 채널만 조회한다: 채널마다 UUSH 첫 페이지(`maxResults=50`) 1회, 정해지지 않은 항목이 남으면 UULF 첫 페이지 1회(실행당 같은 목록은 두 번 부르지 않는다 → 채널당 최대 2회, 12채널 최대 24유닛). **UUSH에 있으면 `short:true`, UULF에 있으면 `short:false`, 둘 다 없으면 필드 없이 다음 실행에 재시도.** 처음 발견(`added`) 24시간(`config.SHORTS_CONFIRM_HOURS`) 뒤에도 둘 다 없으면 `short:false`로 확정한다(라이브 다시보기·예약 영상 등). 백필도 같은 규칙이다. **한 번 정해진 값은 바꾸지 않는다.** 목록이 404면 그 탭에 영상이 없는 것으로 본다
  - 조회 실패(오류·할당량 초과·키 거부)면 그 채널의 항목은 아무것도 바꾸지 않고 다음 실행에 재시도한다(채널 단위 전부-아니면-전무). 할당량 초과·키 거부는 남은 채널 조회도 멈춘다. 영상 수집이 API로 되지 않은 실행(RSS 대체·키 없음·할당량 초과·키 거부·`youtube` 소스 실패)과 `--only`에 `youtube`가 없는 실행에서는 판별을 건너뛴다. 판별 단계의 오류는 종류만 경고로 남기고 실행은 계속한다
  - 비용(추정): 평소에는 새 영상이 있는(판별 대기 항목이 있는) 채널만 부른다 → 새 영상 하루 약 7.5개 기준 하루 약 8~15유닛(기준 약 580의 2% 안팎), 최초 백필 최대 24유닛. `search.list`·`videos.list`는 쓰지 않는다
  - 알려진 한계: 첫 페이지(채널당 최신 50개)만 본다. 업데이터가 24시간 넘게 멈췄다 돌아오면 첫 페이지 밖으로 밀려난 오래된 쇼츠가 24시간 규칙으로 false가 될 수 있다. 새 쇼츠가 UUSH 목록에 나타나기까지의 지연은 측정하지 못했다(미정 → 다음 실행 재시도로 흡수되고, 알림은 그 시점에 아직 미정이면 '쇼츠' 표시 없이 나간다)
  - 실측(2026-10-09 `--dry-run`, 실제 API): 배포본 영상 196개 → 쇼츠 50 · 일반 146 · 미정 0 (정답 기록과 196/196 일치), 조회 채널 12개·API 24회. 같은 상태에서 다시 돌리면 대상 0·API 0회
- 모든 요청: `timeout=10`, 브라우저 형태의 User-Agent, 실패해도 다른 소스는 계속
- 멤버 이름 태깅(`tagging.py`): 풀네임과 이름(예: "리제", "아카네 리제"), 유닛명(에버리스/유니버스/클리셰, 영문 포함)을 사전으로 관리. 여러 명이 걸리면 모두 태그, 하나도 없으면 `all`

## 6. 상태 보관 방식 (커밋 없이)
- 데이터 변경 때문에 30분마다 커밋하지 않는다. 대신 **실행 시작 시 배포된 사이트에서 이전 상태를 읽는다**
  - `https://sora7942.github.io/stella-radar/data/{news,catalog,status}.json` (`?t=<timestamp>`로 캐시 회피)
  - 읽기 실패(최초 배포 전 등) → 저장소의 `site/data/` 파일을 사용
- 사람이 관리하는 `members/songs/events.json`은 항상 저장소 파일을 쓴다
- 새 결과를 `site/data/`에 쓰고 `site/` 전체를 Pages에 배포한다
- 사이트 URL은 `config.py`의 `SITE_URL` (환경변수 `SITE_URL`로 덮어쓰기 가능)

## 7. 디스코드 알림
- 대상: 이번 실행에서 **새로 발견**된 항목 중
  - 유튜브 영상: 게시 시각이 6시간 이내인 것만 (최초 실행 때 RSS 180개가 한꺼번에 오는 것 방지)
  - 공식 공지: 날짜가 2일 이내
  - 음악: 목록에 새로 생긴 곡(최초 전체 채우기 중에는 보내지 않음 — 이전 catalog가 비어 있으면 알림 생략)
  - 방송 시작: `live.since`(방송 시작 시각) 기준. 새 since가 이전에 저장된 since와 **다를 때만** 새 방송으로 알린다(같은 since면 치지직 확인 공백이 얼마나 길었든 알리지 않는다). 단, since가 지금으로부터 1시간(`ALERT_LIVE_MAX_AGE_HOURS`) 넘게 지난 방송은 늦은 알림이라 알리지 않는다. since가 없으면(또는 읽을 수 없으면) 이전 규칙: 이전 `on:false`(또는 이전 항목 없음) → 이번 `on:true`일 때만
  - 알림 판정은 `updater/alerts.py`의 순수 함수. 순서는 방송 → 공지 → 새 곡 → 영상(같은 종류는 최신순)이라 20건을 넘어 잘릴 때 급한 것이 남는다. 공지·새 곡의 "2일"은 달력 기준(날짜만 있는 값)
- 형식: 항목 1개 = 임베드 1개 (제목 링크, 멤버 이름, 멤버 색, 유튜브면 썸네일 이미지). 영상은 알림 시점에 `short`가 true로 정해져 있으면 종류 라벨이 '영상' 대신 '쇼츠'다(아직 미정이면 '영상'). 한 메시지에 임베드 최대 10개, 실행당 최대 2메시지(20개), 넘치면 "외 N건"
- **알림은 배포가 성공한 뒤에 보낸다.** 업데이터(`main.py`)는 디스코드로 보내지 않고, 보낼 알림(웹훅 페이로드)을 `site/` 밖의 파일(`config.ALERTS_FILE` = `out/alerts.json`, `.gitignore` 대상)에 남긴다. 배포 성공 후 단계가 `python send_alerts.py`로 **그 파일만** 읽어 발송한다. 이유: 알림이 배포보다 먼저 나가면 배포 실패 때 다음 실행이 같은 항목을 다시 '처음 본 것'으로 판단해 알림이 중복된다. 대신 발송 단계가 실패하면 그 알림은 다시 시도하지 않는다(최대 한 번)
  - `main.py`는 매 실행 시작에 알림 파일을 지운다(이전 실행·dry-run의 알림이 나중에 나가지 않게). `--dry-run`·`--no-discord`는 파일을 남기지 않는다
  - `send_alerts.py`: 웹훅 URL(`DISCORD_WEBHOOK_URL`)은 이 스크립트만 쓴다. 웹훅이 없거나 발송이 실패해도 종료 코드는 0(배포는 이미 끝남), 경고 로그와 GitHub Actions `::warning::` 주석으로 드러낸다. 발송을 시도한 뒤에는 파일을 지워 중복 발송을 막는다. 모양이 이상한 파일은 보내지 않는다
- 피드 표시 여부: 방송 시작은 디스코드 + 사이트 상단 LIVE 표시만, news 피드에는 넣지 않는다 (`config.LIVE_TO_FEED = False`)

## 8. 실행 옵션
- `python main.py` : 수집 → `site/data/` 갱신 → 보낼 알림을 `out/alerts.json`에 남김 (디스코드로 보내지 않음)
- `python main.py --dry-run` : 데이터 파일은 쓰되 알림 파일은 남기지 않고, 보낼 내용을 콘솔에 출력
- `python send_alerts.py` : `out/alerts.json`의 알림을 `DISCORD_WEBHOOK_URL`로 발송 (`--dry-run`이면 내용만 출력)
- `python main.py --only youtube,news` : 일부 소스만 실행 (디버깅용)
- 로컬 미리보기: `python -m http.server -d site 8000` → `http://localhost:8000`

## 9. GitHub Actions (`update.yml`)
- **정기 실행(주 경로): 외부 cron 서비스(cron-job.org)가 30분마다 GitHub API로 `workflow_dispatch`를 호출한다.** `POST https://api.github.com/repos/sora7942/stella-radar/actions/workflows/update.yml/dispatches`, 본문 `{"ref":"main"}`, 헤더 `Accept`·`Authorization: Bearer <토큰>`·`X-GitHub-Api-Version`·`Content-Type`. 토큰은 fine-grained PAT(이 저장소 하나 · Actions Read/Write만 · 만료 1년). 이렇게 시작된 실행은 Actions 목록에 "Manually run"(`event=workflow_dispatch`)으로 보이며 `no_alerts` 기본값이 false라 알림도 정상 발송된다. 설정 방법은 README
  - 이유: GitHub `schedule`(예약 실행)이 이 저장소에서 한 번도 시작되지 않았다(`*/30` 슬롯 4개 + `7,37` 슬롯 6개, `schedule` 이벤트 실행 0건, 원인 미확정 — PROGRESS 7단계)
  - 외부 cron에 의존한다: cron-job.org 장애, 토큰 만료·삭제가 있으면 갱신이 멈춘다 → 토큰 만료일을 달력에 적어 두고 cron-job.org의 실패 알림을 켠다. 사이트의 "마지막 관측" 시각으로 확인한다
  - **토큰 값은 cron-job.org의 헤더 칸에만 둔다.** 저장소·문서·GitHub Secret·`.env`·로그·커밋에 남기지 않는다(문서에는 `<토큰>`). 비밀 스캔 테스트가 `github_pat_`·`ghp_` 모양을 잡는다(10장)
- 보조 트리거: `schedule: cron "7,37 * * * *"`(30분 간격이되 정각·30분을 비킨다 — GitHub 예약 실행은 정각 부근에 몰려 지연되거나 버려질 수 있다), `workflow_dispatch`(입력 `no_alerts`: 알림 없이 실행 = `main.py --no-discord`, 수동 실행도 이것), `push` (main 브랜치, `site/**`·`updater/**` 외에 `main.py`·`send_alerts.py`·`requirements.txt`·`update.yml` 변경도 포함). 외부 cron과 겹쳐 돌아도 `concurrency`로 순서대로 실행되고 새 항목이 없으면 알림도 없다
- 한 잡(`update`, `environment: github-pages`, `timeout-minutes: 15`)에 모든 단계를 둔다. 액션은 공식 액션의 메이저 버전으로 고정: `checkout@v7`, `setup-python@v7`, `upload-pages-artifact@v5`, `deploy-pages@v5`
- `keepalive.yml`(SPEC 3장 구조에 추가): 매달 1일 빈 커밋. 쓰기 권한(`contents: write`)은 이 워크플로만 갖는다. 데이터를 커밋하지 않아 저장소 활동이 없으면 GitHub가 60일 뒤 예약 실행을 끄기 때문(지금은 외부 cron이 주 경로라 이것은 GitHub `schedule`을 위한 보조 장치)
- `concurrency: { group: pages, cancel-in-progress: false }` — 겹쳐 실행 방지
- 권한: `contents: read`, `pages: write`, `id-token: write`
- 단계: checkout → Python 3.12 + pip 캐시 → `python main.py` → `actions/upload-pages-artifact`(path: `site`) → `actions/deploy-pages` → **`python send_alerts.py`** (7장: 배포가 성공한 뒤에만 도는 마지막 단계. 알림 파일 `out/alerts.json`은 같은 잡의 러너에 남아 있으므로 별도 잡·아티팩트 전달이 필요 없다)
- 업데이터가 실패(예외 종료)해도 배포 단계는 건너뛰고(알림도 나가지 않고), 실행은 실패로 표시 (GitHub 실패 메일). 배포가 실패하면 알림 단계도 돌지 않는다
- Secret: `DISCORD_WEBHOOK_URL` — **`send_alerts.py` 단계의 `env`에만** 넣는다. 업데이터(`main.py`) 단계에는 노출하지 않는다
- Secret: `YOUTUBE_API_KEY` — **`main.py` 단계의 `env`에만** 넣는다(업데이터만 읽는다). 없으면 RSS로 수집한다
- **갱신 정체 감시 `watchdog.yml`**(기능 0-e): 2026-10-07 `waiting`에 남은 `update` 실행 하나가 `pages` 동시 실행 그룹을 잡아 사이트가 약 22.5시간 갱신되지 않았다(외부 cron의 dispatch는 204로 성공해 아무도 몰랐다). `timeout-minutes`는 시작하지 못한 job에는 듣지 않을 수 있어(미확인) 별도 감시를 둔다.
  - 트리거는 `workflow_dispatch`뿐(입력 없음). 외부 cron이 `POST …/actions/workflows/watchdog.yml/dispatches`를 **1시간마다**, `update.yml`을 부르는 것과 **같은 토큰**으로 호출한다(README). 동시 실행 그룹은 `watchdog`(`pages`와 다름, `cancel-in-progress: true` — 점검 자신이 막히면 다음 점검이 대체), 권한은 `actions: write`·`contents: read`뿐, `timeout-minutes: 10`
  - 규칙(값은 `config.WATCHDOG_*`, 판정은 `updater/watchdog.py`의 순수 함수): 배포된 `news.json`의 `updatedAt`이 **90분을 넘게** 지났으면 정체 → `update.yml` 실행 중 `queued`·`waiting`·`in_progress` 상태로 **30분을 넘은** 것을 취소(`cancel`이 409면 `force-cancel`) → 디스코드 경고 1건. 정상이면 사이트 확인 1회 외에는 아무것도 하지 않는다. 사이트를 읽을 수 없으면(판정 불가) 아무것도 취소하지 않는다
  - 경고는 같은 정체(`updatedAt` 기준)로 **처음 한 번 + 6시간마다 한 번**(점검 간격 지터를 위해 10분 여유). 상태를 저장하지 않고, 이전 `watchdog` 실행의 **"경고 발송" 단계가 success였는지**를 Actions API로 읽어 마지막 경고 시각으로 쓴다(단계 이름은 `config.WATCHDOG_ALERT_STEP`). 기록 조회가 실패하면 경고하는 쪽으로 판단한다. 경고가 억제돼도 정체된 실행의 취소는 계속하고 실행 요약에 `::warning::`을 남긴다
  - 흐름: `python watchdog.py`(env: `GITHUB_TOKEN`만)가 경고를 `out/alerts.json`(7장과 같은 형식)에 남기고 `$GITHUB_OUTPUT`에 `alert=true|false`를 쓴다 → 다음 단계 "경고 발송"(`if: steps.check.outputs.alert == 'true'`, env: `DISCORD_WEBHOOK_URL`만)이 `python send_alerts.py`로 보낸다. `watchdog.py`는 웹훅을 읽지 않는다. 토큰은 헤더로만 보내고 오류는 HTTP 상태·예외 종류만 기록한다
  - 한계: 이 감시도 같은 외부 cron에 의존한다(cron-job.org가 통째로 멈추면 경고도 나가지 않는다). 정체된 실행이 없는데 사이트가 멈춘 경우(외부 cron 중단·토큰 만료)는 "정체된 실행은 없어요 — 외부 cron·토큰 확인" 경고로 알린다
- 저장소 Settings → Pages → Source를 **GitHub Actions**로 설정 (README에 안내)

## 10. 테스트 (네트워크 없이)
- `tests/fixtures/`에 실제 응답을 한 번 저장해서 사용: 유튜브 RSS XML, stellive news 목록 HTML, music 목록·상세 HTML, 치지직 live-status JSON, 유튜브 채널 HTML(og:image 부분)
- 파서: 각 fixture에서 기대하는 필드가 나오는지
- 태깅: "아카네 리제 생일 굿즈"→`["lize"]`, "에버리스 1주년"→`["everys"]`, "STELLA MODE:ON"→`["all"]`, 아티스트 "Cliché"→`["cliche"]`
- 병합: 중복 id 무시, `added` 유지, 300개 자르기, 정렬
- 알림 판정: 6시간/2일 규칙, 최초 catalog 채우기 중 미발송, 방송 off→on만
- 이전 상태 로드: 원격 실패 시 로컬 fallback
- 비밀 스캔(`tests/test_secrets_hygiene.py`): 커밋될 파일에 Google API 키·디스코드 웹훅 URL·GitHub 토큰(`github_pat_`·`ghp_` 등)·Anthropic 키(`sk-ant-`) 모양이나 로컬 `.env`의 실제 값이 없는지. 실패 메시지에는 파일 경로만 나온다

## 11. 완료 기준
1. `pytest -q` 전부 통과
2. `python main.py --dry-run` 실행 후 `site/data/news.json`에 유튜브 영상(`yt` 포함)과 공지가 들어 있고, `catalog.json`에 곡이 쌓이고, `status.json`에 아바타 URL이 들어 있다
3. `python -m http.server -d site 8000`으로 열었을 때 멤버 사진·노래 썸네일·영상 썸네일이 보이고 콘솔 에러가 없다
4. GitHub에 올리고 Actions 수동 실행 → Pages 주소에서 같은 화면이 보인다
5. 디스코드에 테스트 알림 1건 도착 (사용자가 요청할 때)
6. 다음 30분 실행(외부 cron이 호출)이 자동으로 돌고 `마지막 관측` 시각이 갱신된다

## 12. 진행 순서
1. 저장소 생성, 받은 파일(site/, SPEC.md, CLAUDE.md) 배치, `python -m http.server -d site`로 현재 화면 확인
2. 유튜브 RSS + 태깅 + 상태 병합 → `--dry-run`으로 news.json 확인
3. 공식 공지·음악 카탈로그 → catalog.json 확인 (최초 채우기 여러 번)
4. 아바타·치지직 → status.json 확인, 강지 치지직 채널 ID 찾아 사용자 확인
5. 디스코드 발송 (dry-run 출력 → 사용자 요청 시 실제 1회)
6. Actions 워크플로 + README → push, Pages 설정, 수동 실행
7. 정기 실행(외부 cron) 확인 후 이전 Claude 예약 작업 끄기 (사용자가 Claude 앱에서)
