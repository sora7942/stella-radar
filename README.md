# 스텔라 레이더 (stella-radar)

스텔라이브(강지 · 1기 에버리스 · 2기 유니버스 · 3기 클리셰 · 단체 · 멤버 개인)의 새 소식, 노래, 팬 게임, 생일·일정을 한곳에서 보는 **비공식 팬 허브**입니다.

- 사이트: https://sora7942.github.io/stella-radar/ (GitHub Pages)
- 30분마다 GitHub Actions가 새 소식을 모아 사이트를 다시 배포하고, 새 영상·공지·방송 시작은 디스코드로 알립니다.
- 공개 저장소의 무료 Actions만 씁니다. 서버·LLM 호출·비용이 없습니다. PC를 꺼도 동작합니다.
- 비공식 사이트이며 스텔라이브와 관련이 없습니다. **이미지는 저장하지 않고** 원본 주소로 링크만 겁니다(프로필 사진·영상 썸네일).

요구사항과 데이터 스키마는 [SPEC.md](SPEC.md), 작업 규칙은 [CLAUDE.md](CLAUDE.md), 진행 기록은 [PROGRESS.md](PROGRESS.md)에 있습니다.

## 어떻게 동작하나

```
update.yml (30분마다 · 수동 · main push)
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
- 사람이 고치는 데이터: `site/data/members.json`, `songs.json`, `events.json`. 업데이터는 읽기만 합니다. 자동 생성: `news.json`, `catalog.json`, `status.json`.

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
python -m http.server -d site 8000           # http://localhost:8000 에서 사이트 미리보기
pytest -q                                    # 테스트 (네트워크·디스코드를 부르지 않음)
```

- `.env.example`을 `.env`로 복사해 값을 채웁니다(`.env`는 커밋되지 않습니다). `YOUTUBE_API_KEY`는 `python main.py`가, `DISCORD_WEBHOOK_URL`은 `python send_alerts.py`만 읽습니다.
- 로컬에서 `main.py`를 `--dry-run` 없이 돌리면 `site/data/*.json`이 바뀝니다. 커밋하지 말고 `git restore site/data`로 되돌리세요(`catalog.json`은 저장소의 시드로 돌아갑니다).
- **`.env`에 웹훅이 있으면 `python send_alerts.py`(`--dry-run` 없이)는 실제로 발송합니다.**

## GitHub에 올릴 때 (최초 1회 설정)

1. **Pages 켜기**: 저장소 *Settings → Pages → Build and deployment → Source*를 **GitHub Actions**로 바꿉니다.
   (CLI: `gh api -X POST repos/<계정>/stella-radar/pages -f build_type=workflow`)
2. **Secret 등록**: *Settings → Secrets and variables → Actions*, 또는 값을 직접 입력하는 방식으로
   ```powershell
   gh secret set YOUTUBE_API_KEY          # YouTube Data API v3 키 (없으면 RSS로 수집)
   gh secret set DISCORD_WEBHOOK_URL      # 디스코드 웹훅 URL (없으면 알림을 보내지 못하고 경고만 남김)
   ```
   키는 Google Cloud에서 *YouTube Data API v3*를 켠 프로젝트의 API 키입니다. 가능하면 키 제한을 "YouTube Data API v3"로만 걸고, IP 제한은 걸지 마세요(Actions의 IP는 매번 다릅니다).
3. **첫 실행**: *Actions → update → Run workflow*. 첫 실행은 배포본이 없어서 시드 데이터에서 시작하며, 2일 이내 공지나 6시간 이내 영상 등이 **실제로 디스코드에 발송**됩니다. 알림 없이 돌리려면 *no_alerts*를 체크하세요.
4. 이후 30분마다 자동으로 돌고 사이트의 "마지막 관측" 시각이 갱신됩니다.

## 알아둘 한계

- **치지직 live-status는 비공식 API**라 언제든 막힐 수 있고, Actions(해외 IP)에서 막힐 수도 있습니다. 막히면 `updater/config.py`의 `ENABLED_SOURCES`에서 `"chzzk"`만 빼세요. 방송 중 표시는 마지막 확인이 2시간을 넘으면 사이트가 숨깁니다.
- **GitHub Actions의 cron은 정확하지 않습니다.** UTC 기준이고 몇 분씩 늦게 돌며, 부하가 크면 건너뛰기도 합니다. 알림 창(영상 6시간·공지 2일·방송 1시간)이 이를 흡수합니다.
- **60일 비활동 방지**: 이 저장소는 데이터를 커밋하지 않아 활동이 없으면 GitHub가 예약 실행을 끕니다. `keepalive.yml`이 한 달에 한 번 빈 커밋을 남깁니다(그래서 로컬에서 push하기 전에 `git pull`이 필요할 수 있습니다).
- **YouTube API 할당량**: 하루 10,000유닛 중 약 580유닛을 씁니다(12채널 × 30분 주기). 초과하면 남은 채널은 RSS로 수집합니다.
- 알림 발송 단계가 실패하면(디스코드 장애 등) 그 알림은 다시 보내지 않습니다. 실행 요약의 경고(Annotations)에서 확인할 수 있습니다.
- 유튜브 RSS는 데이터센터 IP에서 404/500을 내는 일이 있어 대체 수단으로만 씁니다.

## 비밀 관리

- API 키와 웹훅 URL은 코드·로그·커밋에 남기지 않습니다. 키는 URL이 아니라 `X-Goog-Api-Key` 헤더로만 보내고, 오류는 상태 코드와 사유만 기록합니다.
- `pytest -q`는 커밋될 파일 전체를 스캔해서 키 모양의 문자열과 로컬 `.env`의 실제 값이 들어 있지 않은지 확인합니다.
