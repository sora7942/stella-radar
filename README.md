# 스텔라 레이더 (stella-radar)

스텔라이브(강지 · 1기 에버리스 · 2기 유니버스 · 3기 클리셰 · 단체 · 멤버 개인)의 새 소식, 노래, 팬 게임, 생일·일정을 한곳에서 보는 **비공식 팬 허브**입니다.

- 사이트: https://sora7942.github.io/stella-radar/ (GitHub Pages)
- 30분마다 GitHub Actions가 새 소식을 모아 사이트를 다시 배포하고, 새 영상·공지·방송 시작은 디스코드로 알립니다.
- 공개 저장소의 무료 Actions만 씁니다. 서버·비용이 없습니다(LLM은 공식 공지에서 일정을 뽑는 데만 쓰고 월 수백 원 수준, 키가 없으면 그 기능만 꺼집니다). PC를 꺼도 동작합니다.
- 비공식 사이트이며 스텔라이브와 관련이 없습니다. **이미지는 저장하지 않고** 원본 주소로 링크만 겁니다(프로필 사진·영상 썸네일).

요구사항과 데이터 스키마는 [SPEC.md](SPEC.md), 작업 규칙은 [CLAUDE.md](CLAUDE.md), 진행 기록은 [PROGRESS.md](PROGRESS.md)에 있습니다.

## 어떻게 동작하나

```
update.yml (외부 cron이 30분마다 호출 · 수동 · main push · GitHub 예약은 보조)
  1. python main.py        수집 → site/data/ 갱신 → 보낼 알림을 out/alerts.json에 남김
  2. 사이트(site/)를 Pages에 배포
  3. python send_alerts.py 배포가 성공한 뒤에만, out/alerts.json만 읽어 디스코드로 발송
```

| 소스 | 방법 |
|---|---|
| 유튜브 새 영상 (12개 채널) | **YouTube Data API**가 기본. 키가 없거나 할당량이 초과됐거나 키가 거부되면 RSS로 대체 (키 거부는 Actions 실행 요약에 경고가 뜹니다) |
| 공식 공지 · 음악 카탈로그 | stellive.me 목록/상세 HTML |
| 방송 중 표시 | 치지직 live-status (**비공식 API**) |
| 멤버 프로필 사진 | 유튜브 채널 페이지의 `og:image` (하루 1번) |

- 데이터를 커밋하지 않습니다. 실행 때마다 **배포된 사이트의 `data/*.json`을 이전 상태로** 읽고 새 결과를 이어 붙여 다시 배포합니다.
- 알림이 배포보다 먼저 나가면 배포 실패 때 같은 알림이 중복되므로, 알림은 **배포 성공 뒤 별도 단계**에서 보냅니다. 대신 그 단계가 실패하면 그 알림은 다시 시도하지 않습니다(최대 한 번).
- 사람이 고치는 데이터: `site/data/members.json`, `songs.json`, `events.json`. 업데이터는 읽기만 합니다. 자동 생성: `news.json`, `catalog.json`, `status.json`, `auto_events.json`(공지에서 뽑은 일정).

## 로컬에서 실행

Windows + PowerShell, conda 기준입니다.

```powershell
# 최초 1회
conda create -n stella python=3.12 -y; conda activate stella; pip install -r requirements.txt
# 이후 작업 전
conda activate stella

python main.py --dry-run                     # 수집만 (알림은 콘솔에 출력만 하고 파일로 남기지 않음)
python main.py --dry-run --only youtube      # 일부 소스만 (youtube, news, music, avatar, chzzk)
python main.py --dry-run --local-state       # 이전 상태를 배포본 대신 로컬 site/data/에서 읽기
python send_alerts.py --dry-run              # out/alerts.json에 남은 알림의 내용만 확인
python watchdog.py --dry-run                 # 사이트 갱신 정체 점검 (읽기만, 취소·파일 쓰기 없음)
python -m http.server -d site 8000           # http://localhost:8000 에서 사이트 미리보기
pytest -q                                    # 테스트 (네트워크·디스코드를 부르지 않음)
```

- `.env.example`을 `.env`로 복사해 값을 채웁니다(`.env`는 커밋되지 않습니다). `YOUTUBE_API_KEY`·`ANTHROPIC_API_KEY`는 `python main.py`가(**`ANTHROPIC_API_KEY`가 `.env`에 있으면 `python main.py`가 실제로 Claude API를 부릅니다** — 로컬 확인은 `--only` 로 범위를 줄이세요), `DISCORD_WEBHOOK_URL`은 `python send_alerts.py`만 읽습니다.
- 로컬에서 `main.py`를 `--dry-run` 없이 돌리면 `site/data/*.json`이 바뀝니다. 커밋하지 말고 `git restore site/data`로 되돌리세요(`catalog.json`은 저장소의 시드로 돌아갑니다).
- **`.env`에 웹훅이 있으면 `python send_alerts.py`(`--dry-run` 없이)는 실제로 발송합니다.**

## GitHub에 올릴 때 (최초 1회 설정)

1. **Pages 켜기**: 저장소 *Settings → Pages → Build and deployment → Source*를 **GitHub Actions**로 바꿉니다.
   (CLI: `gh api -X POST repos/<계정>/stella-radar/pages -f build_type=workflow`)
2. **Secret 등록**: *Settings → Secrets and variables → Actions*, 또는 값을 직접 입력하는 방식으로
   ```powershell
   gh secret set YOUTUBE_API_KEY          # YouTube Data API v3 키 (없으면 RSS로 수집)
   gh secret set DISCORD_WEBHOOK_URL      # 디스코드 웹훅 URL (없으면 알림을 보내지 못하고 경고만 남김)
   gh secret set ANTHROPIC_API_KEY        # Claude API 키 (없으면 공지 일정 추출만 건너뜀. main.py 단계에만 전달됨)
   ```
   키는 Google Cloud에서 *YouTube Data API v3*를 켠 프로젝트의 API 키입니다. 가능하면 키 제한을 "YouTube Data API v3"로만 걸고, IP 제한은 걸지 마세요(Actions의 IP는 매번 다릅니다).
3. **첫 실행**: *Actions → update → Run workflow*. 첫 실행은 배포본이 없어서 시드 데이터에서 시작하며, 2일 이내 공지나 6시간 이내 영상 등이 **실제로 디스코드에 발송**됩니다. 알림 없이 돌리려면 *no_alerts*를 체크하세요.
4. **30분마다 자동으로 돌리기**: 아래 「외부 cron으로 30분마다 실행하기」를 설정하세요. GitHub 자체의 `schedule`은 이 저장소에서 작동하지 않았습니다(아래 「알아둘 한계」). 정기 실행이 돌면 사이트의 "마지막 관측" 시각이 갱신됩니다.

## 외부 cron으로 30분마다 실행하기 (cron-job.org)

**왜**: 이 저장소에서는 GitHub의 `schedule`(예약 실행)이 처음 한동안 한 번도 시작되지 않았고 이후에도 간헐적으로만 시작됩니다(자세한 내용은 아래 「알아둘 한계」). 그래서 외부 cron 서비스가 GitHub API로 `workflow_dispatch`를 30분마다 호출해 실행합니다. 이렇게 시작된 실행은 Actions 목록에 **"Manually run"**(`event=workflow_dispatch`)으로 보이고, 다른 점은 없습니다(`no_alerts` 입력은 기본값 false라 알림도 정상 발송).

**1. 토큰 만들기** (GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token)
- *Repository access*: **Only select repositories** → 이 저장소(`stella-radar`) 하나만
- *Repository permissions*: **Actions: Read and write** 하나만 (Metadata: Read-only는 자동으로 붙습니다). 다른 권한은 주지 않습니다.
- *Expiration*: 최대 1년. **만료일을 달력에 적어 두세요** — 만료되면 외부 호출이 401/403으로 실패하고 사이트 갱신이 멈춥니다.

**2. cron-job.org에서 작업 만들기** (무료 계정으로 충분합니다. 다른 cron 서비스도 같습니다. 화면 이름은 서비스마다 조금 다릅니다)

| 항목 | 값 |
|---|---|
| URL | `https://api.github.com/repos/<계정>/stella-radar/actions/workflows/update.yml/dispatches` |
| 요청 방법 | `POST` |
| 본문 | `{"ref":"main"}` |
| 헤더 | `Accept: application/vnd.github+json` · `Authorization: Bearer <토큰>` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json` |
| 스케줄 | 30분마다 (예: 매시 0분·30분) |

- 성공하면 GitHub가 **204 No Content**를 돌려줍니다.
- 서비스의 **실패 알림**(failure notification) 기능을 켜 두세요. 토큰이 만료되거나 서비스 호출이 실패하면 사이트가 조용히 멈추기 때문입니다.

**3. 확인**: Actions → update에서 "Manually run" 실행이 30분마다 생기는지, 사이트의 "마지막 관측"이 갱신되는지 봅니다. 터미널에서 한 번 시험하려면(토큰은 환경변수로 넣고 명령줄에 직접 쓰지 마세요):

```powershell
curl.exe -i -X POST `
  -H "Accept: application/vnd.github+json" `
  -H "Authorization: Bearer $env:GITHUB_PAT" `
  -H "X-GitHub-Api-Version: 2022-11-28" `
  -H "Content-Type: application/json" `
  -d '{"ref":"main"}' `
  https://api.github.com/repos/<계정>/stella-radar/actions/workflows/update.yml/dispatches
```

**토큰 관리**
- 토큰 값은 **cron-job.org의 헤더 칸에만** 둡니다. 저장소 파일·GitHub Secret·`.env`·이슈·채팅·문서 어디에도 붙여 넣지 않습니다(이 저장소의 문서에는 `<토큰>` 같은 자리표시자만 씁니다).
- 유출됐다고 의심되면 GitHub의 토큰 목록에서 바로 **Revoke(삭제)** 하고 새로 발급해 cron-job.org의 헤더를 바꿉니다.
- 권한을 이 저장소의 Actions 하나로 좁혀 두었기 때문에 유출되어도 이 저장소의 워크플로를 실행·취소하는 정도가 한계입니다. 그래도 만료를 1년으로 두고 정기적으로 교체하세요.

## 갱신 정체 감시 (watchdog)

**왜**: 2026-10-07 `update` 실행 하나가 시작도 못 하고 `waiting`에 남아 동시 실행 그룹(`pages`)을 붙잡았고, 이후 실행이 줄줄이 취소되어 사이트가 약 22.5시간 갱신되지 않았습니다. 외부 cron의 호출 자체는 204로 성공하므로 cron-job.org의 실패 알림도 울리지 않았습니다. `update.yml`의 `timeout-minutes: 15`는 실행이 시작된 뒤 멈춘 경우만 막고(시작하지 못하고 `waiting`에 남는 경우에 적용되는지는 확인하지 못했습니다), 그 경우를 `watchdog.yml`이 맡습니다.

**무엇을 하나** (`watchdog.yml` → `python watchdog.py`, 규칙 값은 `updater/config.py`의 `WATCHDOG_*`)
- 배포된 사이트 `data/news.json`의 `updatedAt`이 **90분을 넘게** 지났으면 정체로 봅니다. 정상이면 **아무것도 하지 않습니다**(사이트 확인 1회뿐, GitHub API도 부르지 않음).
- 정체면 `update.yml` 실행 중 `queued`·`waiting`·`in_progress` 상태로 **30분을 넘은** 것을 취소합니다(일반 취소가 거부되면 강제 취소). 정상 실행은 몇 분이면 끝나므로 진행 중인 새 실행은 건드리지 않습니다.
- 디스코드에 경고를 보냅니다. **같은 정체로는 처음 한 번, 이후 6시간마다 한 번만** 보냅니다(취소는 경고 억제와 상관없이 계속 합니다). 정체된 실행이 없으면 "외부 cron·토큰을 확인하세요"라고 알립니다.
- 사이트를 읽을 수 없으면(판정 불가) **아무것도 취소하지 않고** 경고 주석만 남깁니다.
- 경고를 이미 보냈는지는 따로 저장하지 않고, 이전 점검 실행의 **"경고 발송" 단계가 success였는지**를 GitHub API로 읽어 판단합니다(그래서 `watchdog.yml`의 그 단계 이름을 바꾸면 안 됩니다 — 테스트가 지킵니다). 기록을 읽지 못하면 경고를 보내는 쪽으로 판단합니다.
- 권한은 `actions: write`(실행 조회·취소)와 `contents: read`뿐이고, 동시 실행 그룹은 `update`와 다른 `watchdog`입니다(update가 `pages`에서 막혀 있어도 점검은 돕니다). 디스코드 웹훅 Secret은 "경고 발송" 단계에만 들어갑니다.

**cron-job.org에 두 번째 작업 만들기** (토큰은 `update.yml`을 부르는 작업과 **같은 토큰**을 씁니다. 그 토큰의 *Actions: Read and write*가 이 워크플로 호출도 포함합니다)

| 항목 | 값 |
|---|---|
| URL | `https://api.github.com/repos/<계정>/stella-radar/actions/workflows/watchdog.yml/dispatches` |
| 요청 방법 | `POST` |
| 본문 | `{"ref":"main"}` |
| 헤더 | `Accept: application/vnd.github+json` · `Authorization: Bearer <토큰>` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json` |
| 스케줄 | **1시간마다**, update 작업과 겹치지 않는 분(예: 매시 15분) |

- `watchdog.yml`이 `main`에 올라가 있어야 호출이 성공합니다(없으면 404). 성공하면 204입니다.
- **확인**: Actions → watchdog에서 "Manually run" 실행을 한 번 돌려 보세요. 정상이면 모든 단계가 초록이고 **"경고 발송" 단계는 건너뜀(skipped)** 입니다. 로그에 `정상: 마지막 갱신 N분 전`이 나옵니다.
- 로컬에서 읽기만 해 보려면 `python watchdog.py --dry-run`(취소·파일 쓰기 없음, 토큰 없이도 동작, GitHub 비인증 한도 시간당 60회 안에서만)입니다.
- **한계**: 이 감시도 같은 외부 cron(cron-job.org)에 의존합니다. cron-job.org가 통째로 멈추면 두 작업이 다 멈춰 경고도 나가지 않으니, 서비스의 실패 알림 설정은 계속 필요합니다. 감시는 "사이트가 멈췄는데 아무도 모르는" 시간을 몇 시간 안으로 줄이는 장치입니다.

## 알아둘 한계

- **치지직 live-status는 비공식 API**라 언제든 막힐 수 있고, Actions(해외 IP)에서 막힐 수도 있습니다. 막히면 `updater/config.py`의 `ENABLED_SOURCES`에서 `"chzzk"`만 빼세요. 방송 중 표시는 마지막 확인이 2시간을 넘으면 사이트가 숨깁니다.
- **GitHub `schedule`(예약 실행)은 이 저장소에서 믿을 수 없습니다.** `*/30 * * * *`로 워크플로를 올린 2026-10-06 18:28부터 `7,37 * * * *`로 바꾼 뒤 23:07 슬롯까지 슬롯 10개 동안 한 번도 시작되지 않았습니다. 이후 실행 목록에는 `schedule` 실행이 간헐적으로 보이지만(10-07 낮~밤 약 13시간, 슬롯 약 26개 중 3건 확인) 정기 실행을 맡길 수준은 아닙니다. GitHub 상태는 정상이었고 설정 문제도 찾지 못했습니다(원인은 확정하지 못했습니다). 공식 문서는 고부하 때(특히 매 정각 부근) 지연되거나 큐의 작업이 버려질 수 있다고 합니다. 그래서 정기 실행은 위의 **외부 cron**이 맡고, `update.yml`의 `schedule`(`7,37`)은 보조로 남겨 두었습니다. 둘이 겹쳐 돌아도 `concurrency`로 순서대로 실행되고 새 항목이 없으면 알림도 없습니다.
- **외부 cron에 의존합니다.** cron-job.org 장애, 토큰 만료·삭제, 서비스 쪽 설정 변경이 있으면 사이트 갱신이 멈춥니다. 실패 알림 설정과 토큰 만료일 관리가 필요합니다.
- **알림 창**: 영상 6시간·공지 2일·방송 시작 1시간. 실행이 오래 비면(예: 예약 실행이 안 돌 때) 그 사이 시작한 **방송 알림은 시작 1시간이 지나면 보내지 않아 사라집니다.** 실제로 18:32~20:14 사이에 시작한 방송 3건이 이 규칙으로 제외됐습니다(영상·공지는 창이 길어 대부분 살아남습니다).
- **60일 비활동 방지**: 이 저장소는 데이터를 커밋하지 않아 활동이 없으면 GitHub가 예약(`schedule`) 실행을 끕니다. `keepalive.yml`이 한 달에 한 번 빈 커밋을 남깁니다. 지금은 외부 cron이 주 경로라서 이것은 GitHub 예약 실행을 위한 보조 장치입니다(빈 커밋이 쌓이므로 로컬에서 push하기 전에 `git pull`이 필요할 수 있습니다).
- **치지직 live-status(v2)는 해외 IP에서 방송 단위로 막힐 수 있습니다.** 후야 방송이 20:14 이후 Actions 실행마다 HTTP 500이었는데(같은 요청이 한국 PC에서는 200), 시험해 보니 응답이 `code 9004 "해외 시청 불가능한 컨텐츠 입니다."`였습니다. 같은 해외 IP에서 `polling/v3`는 200이어서, v2가 5xx면 v3로 대체해 읽습니다(`updater/config.py`의 `CHZZK_LIVE_STATUS_URLS`; 둘 다 비공식 API라 바뀔 수 있습니다). 둘 다 5xx면 1초 뒤 한 번 더 돌고, 그래도 실패한 멤버는 이전 값이 유지되어 그 멤버의 방송 중 표시와 방송 시작 알림만 갱신되지 않습니다. 같은 멤버가 **연속 3회** 실패하면 Actions 실행 요약(Annotations)에 경고가 올라옵니다(`status.json`의 `liveFails`가 연속 실패 횟수). Actions에서 대체가 실제로 동작하는 것을 확인했습니다(2026-10-08 실행 로그: 후야 `HTTP 500 (code 9004) — 다음 엔드포인트 시도` 뒤 실패 없이 11명 처리).
- **YouTube API 할당량**: 하루 10,000유닛 중 약 580유닛을 씁니다(12채널 × 30분 주기). 초과하면 남은 채널은 RSS로 수집합니다.
- 알림 발송 단계가 실패하면(디스코드 장애 등) 그 알림은 다시 보내지 않습니다. 실행 요약의 경고(Annotations)에서 확인할 수 있습니다.
- 유튜브 RSS는 데이터센터 IP에서 404/500을 내는 일이 있어 대체 수단으로만 씁니다.

## 비밀 관리

- API 키와 웹훅 URL은 코드·로그·커밋에 남기지 않습니다. 키는 URL이 아니라 `X-Goog-Api-Key` 헤더로만 보내고, 오류는 상태 코드와 사유만 기록합니다.
- `pytest -q`는 커밋될 파일 전체를 스캔해서 키 모양의 문자열과 로컬 `.env`의 실제 값이 들어 있지 않은지 확인합니다.
- 외부 cron용 GitHub 토큰은 저장소 어디에도 두지 않습니다(cron-job.org의 헤더 칸에만). 위 스캔 테스트는 Google API 키·디스코드 웹훅·GitHub 토큰(`github_pat_`·`ghp_` 등)·Anthropic 키(`sk-ant-`) 모양을 검사하지만, 그래도 문서를 쓸 때 토큰 자리에는 `<토큰>`만 적으세요.
