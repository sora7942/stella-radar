# SPEC — stella-radar

스텔라이브(강지 · 1기 에버리스 · 2기 유니버스 · 3기 클리셰 · 단체 · 멤버 개인)의 새 소식, 노래, 팬 게임, 생일·일정을 한곳에서 보는 **비공식 팬 허브 사이트**.
GitHub Pages(공개 저장소)로 서비스하고, GitHub Actions가 30분마다 새 소식을 모아 사이트를 다시 배포하며, 새 소식은 디스코드 웹훅으로 알린다.

> 이전 버전은 Claude 아티팩트였다. 아티팩트는 외부 이미지를 못 불러오고 유튜브 RSS를 못 읽어서 옮긴다.
> 프론트엔드(`site/index.html`)는 이미 완성되어 있다. 이 SPEC의 주된 구현 대상은 **업데이터와 배포 워크플로**다.

## 1. 목표
- `https://sora7942.github.io/stella-radar/`에서 사이트가 열린다
- 멤버 프로필 사진(유튜브 채널 이미지)과 노래·영상 썸네일(유튜브)이 **링크(핫링크)로** 보인다. 이미지를 저장소에 복사하지 않는다
- 30분마다(실제로는 GitHub 사정으로 몇 분씩 밀림) 다음을 반영한다
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
├─ .github/workflows/update.yml   # 30분마다 수집 → 배포 (+ main push, 수동 실행)
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
│  ├─ alerts.py                   # 알림 대상 판정 (순수 함수, 7장)
│  └─ discord.py                  # 임베드 생성·발송·dry-run 출력
├─ tests/ (fixtures/ 포함)
├─ main.py                        # 수집 → site/data 갱신 → out/alerts.json (보낼 알림)
├─ send_alerts.py                 # 배포 성공 뒤 out/alerts.json만 읽어 디스코드로 발송
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
- `avatar`: 유튜브 채널 페이지의 `og:image`. 크기 파라미터만 `=s900` → `=s240`으로 바꿔 저장한다(같은 서버·같은 이미지, `config.AVATAR_SIZE`). 하루 1번 갱신, 실패하면 이전 값 유지
- `live`: 치지직 방송 상태. 꺼져 있으면 `{"on":false,"checkedAt":"..."}`
- `live.checkedAt`: 치지직을 마지막으로 **성공적으로 확인한** 시각. 요청이 실패한 멤버는 이전 live 값과 이전 checkedAt이 그대로 남는다. 사이트는 checkedAt이 2시간 넘게 지났거나 없는 LIVE는 표시하지 않는다(소스를 끄거나 계속 실패해도 오래된 LIVE가 남지 않게)

### songs.json / events.json (사람이 관리)
- songs: `{"items":[{"date","title","who","kind","note","tracks"?, "yt": null|"<videoId>"}]}` — `yt`가 null이면 사이트가 catalog에서 같은 제목을 찾아 채움
- events: `{"items":[{"id","start","end"?,"title","who","note","url"}]}`

## 5. 수집 소스
| 소스 | 방법 | 비고 |
|---|---|---|
| 유튜브 새 영상 | `https://www.youtube.com/feeds/videos.xml?channel_id=<UC…>` (12개 채널) | 채널당 최신 15개. 쇼츠·라이브 다시보기·예정 프리미어 포함. 공식 채널 영상은 제목에서 멤버 이름을 찾아 태그, 없으면 `all` |
| 공식 공지 | `https://stellive.me/news` 목록 HTML | Rhymix 기반. 제목·날짜·카테고리·`/news/<번호>` 파싱. 첫 페이지만 |
| 공식 음악 | `https://stellive.me/music` 목록 + `/music/<번호>` 상세 | 상세는 **처음 보는 번호만** 가져온다(실행당 최대 40개, 요청 간 0.5초). 최초 실행 때 전체(약 290곡)를 여러 번에 나눠 채움. 새 곡은 news에도 `음악`으로 추가 |
| 치지직 방송 | `https://api.chzzk.naver.com/polling/v2/channels/<id>/live-status` | **비공식 API**. `content.status == "OPEN"`, `content.liveTitle`. Actions(해외 IP)에서 막히면 이 소스만 끄고 사용자에게 보고 |
| 유튜브 프로필 | `https://www.youtube.com/channel/<UC…>` HTML의 `og:image` | 하루 1번 |

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
- 형식: 항목 1개 = 임베드 1개 (제목 링크, 멤버 이름, 멤버 색, 유튜브면 썸네일 이미지). 한 메시지에 임베드 최대 10개, 실행당 최대 2메시지(20개), 넘치면 "외 N건"
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
- 트리거: `schedule: cron "*/30 * * * *"`, `workflow_dispatch`, `push` (main 브랜치, `site/**` 또는 `updater/**` 변경)
- `concurrency: { group: pages, cancel-in-progress: false }` — 겹쳐 실행 방지
- 권한: `contents: read`, `pages: write`, `id-token: write`
- 단계: checkout → Python 3.12 + pip 캐시 → `python main.py` → `actions/upload-pages-artifact`(path: `site`) → `actions/deploy-pages` → **`python send_alerts.py`** (7장: 배포가 성공한 뒤에만 도는 마지막 단계. 알림 파일 `out/alerts.json`은 같은 잡의 러너에 남아 있으므로 별도 잡·아티팩트 전달이 필요 없다)
- 업데이터가 실패(예외 종료)해도 배포 단계는 건너뛰고(알림도 나가지 않고), 실행은 실패로 표시 (GitHub 실패 메일). 배포가 실패하면 알림 단계도 돌지 않는다
- Secret: `DISCORD_WEBHOOK_URL` — **`send_alerts.py` 단계의 `env`에만** 넣는다. 업데이터(`main.py`) 단계에는 노출하지 않는다
- 저장소 Settings → Pages → Source를 **GitHub Actions**로 설정 (README에 안내)

## 10. 테스트 (네트워크 없이)
- `tests/fixtures/`에 실제 응답을 한 번 저장해서 사용: 유튜브 RSS XML, stellive news 목록 HTML, music 목록·상세 HTML, 치지직 live-status JSON, 유튜브 채널 HTML(og:image 부분)
- 파서: 각 fixture에서 기대하는 필드가 나오는지
- 태깅: "아카네 리제 생일 굿즈"→`["lize"]`, "에버리스 1주년"→`["everys"]`, "STELLA MODE:ON"→`["all"]`, 아티스트 "Cliché"→`["cliche"]`
- 병합: 중복 id 무시, `added` 유지, 300개 자르기, 정렬
- 알림 판정: 6시간/2일 규칙, 최초 catalog 채우기 중 미발송, 방송 off→on만
- 이전 상태 로드: 원격 실패 시 로컬 fallback

## 11. 완료 기준
1. `pytest -q` 전부 통과
2. `python main.py --dry-run` 실행 후 `site/data/news.json`에 유튜브 영상(`yt` 포함)과 공지가 들어 있고, `catalog.json`에 곡이 쌓이고, `status.json`에 아바타 URL이 들어 있다
3. `python -m http.server -d site 8000`으로 열었을 때 멤버 사진·노래 썸네일·영상 썸네일이 보이고 콘솔 에러가 없다
4. GitHub에 올리고 Actions 수동 실행 → Pages 주소에서 같은 화면이 보인다
5. 디스코드에 테스트 알림 1건 도착 (사용자가 요청할 때)
6. 다음 30분 예약 실행이 자동으로 돌고 `마지막 관측` 시각이 갱신된다

## 12. 진행 순서
1. 저장소 생성, 받은 파일(site/, SPEC.md, CLAUDE.md) 배치, `python -m http.server -d site`로 현재 화면 확인
2. 유튜브 RSS + 태깅 + 상태 병합 → `--dry-run`으로 news.json 확인
3. 공식 공지·음악 카탈로그 → catalog.json 확인 (최초 채우기 여러 번)
4. 아바타·치지직 → status.json 확인, 강지 치지직 채널 ID 찾아 사용자 확인
5. 디스코드 발송 (dry-run 출력 → 사용자 요청 시 실제 1회)
6. Actions 워크플로 + README → push, Pages 설정, 수동 실행
7. 예약 실행 확인 후 이전 Claude 예약 작업 끄기 (사용자가 Claude 앱에서)
