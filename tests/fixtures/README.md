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
| `youtube_channel_lize.html` | 채널 페이지 | 1.6MB 중 `og:*` meta만 |
| `chzzk_live_close.json` | 치지직 live-status (리제) | 방송 종료 상태 실제 응답 |
| `chzzk_live_open.json` | — | **합성**: 위 응답에서 `status`=`OPEN`, `liveTitle`, `openDate`, `closeDate`만 바꿈 (방송 중인 실제 응답을 캡처하지 못해서) |
