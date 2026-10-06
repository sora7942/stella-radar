# tests/fixtures

실제 응답을 한 번 받아 **잘라서** 저장한 것. 테스트는 이 파일만 읽고 네트워크를 쓰지 않는다.
캡처: 2026-10-06 (KST). 용량 때문에 목록은 앞쪽 일부 + 구조가 다른 행만 남겼고, 구조(클래스명·계층)는 원본 그대로다.
stellive.me 레이아웃이 바뀌면 파서가 0건을 내고 실패하도록 해 두었으니, 그때 이 파일들을 다시 캡처한다.

| 파일 | 원본 | 비고 |
|---|---|---|
| `stellive_news_list.html` | `https://stellive.me/news` | 실제 첫 페이지는 360건 전부. 여기엔 16건(분류 5종, 제로폭 공백 제목 1건 포함) |
| `stellive_music_list.html` | `https://stellive.me/music` | 실제 286건 중 29건. 그룹·외부 아티스트·졸업생·`A x B`/`A & B` 행 포함. 날짜·분류·유튜브 ID는 목록에 없음 |
| `stellive_music_detail_cover_13638.html` | `/music/13638` | 상세의 `a.category`가 **멤버 이름**(하위 분류)이라 COVER가 나오지 않음 → 분류는 탭 페이지로 판정 |
| `stellive_music_detail_ep_12876.html` | `/music/12876` | `a.category`가 `EP` |
| `stellive_music_category_ep.html` | `/music/category/8591` | EP 탭 전체(7건, 1페이지) |
| `stellive_music_category_cover_p1.html` | `/music/category/279` | COVER 탭 1페이지 앞 5건 + 페이지네이션(`?page=2` 링크 있음). 탭은 20건씩 페이지가 나뉨 |
| `youtube_rss_lize.xml` | 아카네 리제 채널 RSS | 15건 전체. `published`는 UTC |
| `youtube_rss_official.xml` | 스텔라이브 공식 채널 RSS | 15건 전체. 제목 태깅 케이스 |
| `youtube_channel_lize.html` | 채널 페이지 | 1.6MB 중 `og:*` meta만. 메타가 `<head>` 안에 있는 **옛 배치** (캡처 당시) |
| `youtube_channel_kangji.html` | 강지 채널 페이지 | 2.4MB 중 `og:*`~`fb:app_id` 메타 구역을 **한 글자도 바꾸지 않고** 가져와, 실제와 같은 배치(`</head>` **뒤**, body 안)로 조립한 축약본. 2026-10-06 실측: `</head>` 710,566번째 글자, `og:title` 764,769번째. `og:description`에 강지 치지직 채널 링크가 들어 있다. 나머지(`<title>`, `ytInitialData`)는 축약 |
| `chzzk_live_close.json` | 치지직 live-status (리제) | 방송 종료 상태 실제 응답 |
| `chzzk_live_v3_close.json` | 치지직 `polling/v3` live-status (리제) | 방송 종료 상태 실제 응답 (2026-10-07). v2 응답과 `content` 키 51개가 같다 — v3를 대체 엔드포인트로 쓰는 근거 |
| `chzzk_live_open.json` | — | **합성**: 위 응답에서 `status`=`OPEN`, `liveTitle`, `openDate`, `closeDate`만 바꿈 (방송 중인 실제 응답을 캡처하지 못해서) |

## YouTube Data API 응답 (2026-10-06 캡처, `youtube_api_*.json`)
**실제 응답이고 API 키는 들어 있지 않다**(키는 요청 헤더 `X-Goog-Api-Key`로만 보냈고 응답 본문에는 나오지 않는다. 저장 전에 키 문자열·`AIza…` 형식이 없는지 검사했고, `tests/test_secrets_hygiene.py`가 저장소를 계속 검사한다). 표기만 압축(공백 없는 JSON)했다.

| 파일 | 원본 | 비고 |
|---|---|---|
| `youtube_api_channels.json` | `channels.list?part=contentDetails&id=<12개 채널>` | 12개 채널 전부. `relatedPlaylists.uploads`가 전부 `UU`+채널 ID(앞 `UC` 제외)와 일치 |
| `youtube_api_playlist_lize.json` | `playlistItems.list?part=snippet,contentDetails&maxResults=15` | 리제 업로드 재생목록 15개. 프리미어로 올라온 커버곡(`FzefgoF26Ac`: 예정 08:30:00Z, `videoPublishedAt`=실제 시작 08:30:07Z) 포함 |
| `youtube_api_playlist_kangji.json` | 〃 | 강지 15개. **쇼츠** 포함 — 재생목록 항목에는 쇼츠 표시가 없다(`contentDetails`는 `videoId`·`videoPublishedAt`뿐) |
| `youtube_api_playlist_official.json` | 〃 | 공식 채널 15개 (제목 태깅 시험) |
| `youtube_api_videos_sample.json` | `videos.list?part=snippet,contentDetails,liveStreamingDetails,status` | 위 영상 중 라이브·프리미어 지난 방송 5개 + 쇼츠 4개. **설명·썸네일 등 쓰지 않는 필드는 뺐다.** 수집기는 `videos.list`를 쓰지 않고, 쇼츠·라이브가 어떻게 보이는지 기록하려고 둔 것 |
| `youtube_api_error_badkey.json` | 엉터리 키로 보낸 요청 | **실제** 400 `badRequest` ("API key not valid") |
| `youtube_api_error_nokey.json` | 키 없이 보낸 요청 | **실제** 403 `forbidden` — 403이어도 할당량 초과(`quotaExceeded`)가 아니다 |
| `youtube_api_error_quota.json` | — | **합성**: 일일 할당량 초과를 실제로 만들 수 없어 Google의 오류 형식(`reason: quotaExceeded`)을 따라 만들었다 |
| `youtube_api_error_playlist_not_found.json` | — | **합성**: 낡은 캐시(`playlistNotFound`, 404) 형식 |
