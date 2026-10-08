"""쇼츠 판별이 main.py 흐름에 어떻게 붙는가 (기능 2-1, (c) UUSH 방식). test_main.py의 가짜 네트워크·헬퍼를 그대로 쓴다. 네트워크 없음.
핵심: ① API로 수집한 실행에서만 판별한다(RSS 대체·--only news는 건너뜀) ② 병합 뒤·저장 앞이라 기존 항목 백필과 미정 재시도가 된다
③ 한 번 정해진 값은 불변, 24시간 뒤 미정은 false ④ 판별이 실패해도 실행은 성공 ⑤ 알림 시점에 쇼츠로 확인된 영상만 '쇼츠' 라벨."""
import json

import pytest
import requests

import main as app
from conftest import ROOT  # noqa: F401
from fakeapi import KANGJI as KANGJI_YT, KEY, LIZE as LIZE_YT, FakeApi, fx, http_error, uploads_of
from test_main import API_URL, T1, T2, Net, api_run, data_dir, read, written_text  # noqa: F401  (data_dir은 test_main의 fixture)
from updater import config

SH = lambda cid: "UUSH" + cid[2:]  # noqa: E731
LF = lambda cid: "UULF" + cid[2:]  # noqa: E731


def pl(*vids):
    return {"kind": "youtube#playlistItemListResponse", "items": [{"contentDetails": {"videoId": v}} for v in vids]}


def vids_of(fixture):
    return [e["contentDetails"]["videoId"] for e in fx(fixture)["items"]]


def news_videos(data_dir):
    return {i["yt"]: i for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-")}


def shorts_calls(fake):
    """쇼츠 판별이 부른 목록 (UUSH·UULF 재생목록)"""
    return [u for u, _ in fake.calls if "playlistId=UUSH" in u or "playlistId=UULF" in u]


def test_an_api_run_fills_short_true_false_and_leaves_the_rest_undecided(data_dir):
    ids = vids_of("youtube_api_playlist_lize.json")
    fake = FakeApi(playlists={SH(LIZE_YT): pl(ids[0], ids[1]), LF(LIZE_YT): pl(ids[2])})
    assert api_run(data_dir, Net(api=fake), T1, "--only", "youtube") == 0
    by = news_videos(data_dir)
    assert by[ids[0]]["short"] is True and by[ids[1]]["short"] is True and by[ids[2]]["short"] is False
    assert "short" not in by[ids[3]]  # 두 목록 어디에도 없고 방금 처음 봤다 → 필드 없이 다음 실행에 재시도
    assert all("short" not in v for v in by.values() if v["source"] != "아카네 리제 유튜브")  # 다른 채널은 빈 목록 → 전부 미정


def test_decided_values_stay_and_undecided_ones_are_confirmed_false_after_24_hours(data_dir):
    ids = vids_of("youtube_api_playlist_lize.json")
    api_run(data_dir, Net(api=FakeApi(playlists={SH(LIZE_YT): pl(ids[0]), LF(LIZE_YT): pl(ids[2])})), T1, "--only", "youtube")
    # 30분 뒤: 목록이 정반대를 말해도 정해진 값은 그대로이고, 미정은 여전히 미정이다
    fake2 = FakeApi(playlists={SH(LIZE_YT): pl(ids[2]), LF(LIZE_YT): pl(ids[0])})
    api_run(data_dir, Net(api=fake2), T2, "--only", "youtube", "--local-state")
    by = news_videos(data_dir)
    assert by[ids[0]]["short"] is True and by[ids[2]]["short"] is False and "short" not in by[ids[3]]
    # 처음 본 지 24시간이 지나면 미정은 일반 영상으로 확정된다
    api_run(data_dir, Net(api=FakeApi()), "2026-10-07T10:00:00+09:00", "--only", "youtube", "--local-state")
    by = news_videos(data_dir)
    assert all(isinstance(v["short"], bool) for v in by.values()) and by[ids[0]]["short"] is True and by[ids[3]]["short"] is False
    # 판별할 것이 없으면 목록을 부르지 않는다 (수집 12회뿐)
    fake4 = FakeApi()
    api_run(data_dir, Net(api=fake4), "2026-10-07T10:30:00+09:00", "--only", "youtube", "--local-state")
    assert shorts_calls(fake4) == [] and fake4.endpoints() == ["playlistItems"] * 12


def test_existing_videos_without_short_are_backfilled_by_the_same_rules(data_dir):
    """배포본(이전 상태)에 이미 있는 영상 — short 필드가 없고 added가 오래됐다. 병합 밖 단계라서 기존 항목도 채워진다."""
    ids = vids_of("youtube_api_playlist_lize.json")
    api_run(data_dir, Net(api=FakeApi()), "2026-09-01T10:00:00+09:00", "--only", "youtube")  # 한 달 전에 처음 봤고 (그때는 판별이 없던 것처럼)
    doc = read(data_dir, "news")
    for it in doc["items"]:
        it.pop("short", None)
    (data_dir / "news.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    fake = FakeApi(playlists={SH(LIZE_YT): pl(ids[0]), LF(LIZE_YT): pl(ids[1])})
    api_run(data_dir, Net(api=fake), T1, "--only", "youtube", "--local-state")
    by = news_videos(data_dir)
    assert by[ids[0]]["short"] is True and by[ids[1]]["short"] is False
    assert all(v["short"] is False for k, v in by.items() if k not in ids[:1])  # 어디에도 없고 24시간이 지났다 → 확정


def test_shorts_calls_are_one_per_list_per_channel_with_pending_items(data_dir):
    fake = FakeApi()
    api_run(data_dir, Net(api=fake), T1, "--only", "youtube")
    calls = shorts_calls(fake)
    assert len(calls) == 6 and len(set(calls)) == 6  # 영상이 있는 3채널 × (UUSH, UULF), 같은 목록을 두 번 부르지 않는다
    assert all("maxResults=50" in u and "part=contentDetails" in u for u in calls)
    assert set(fake.endpoints()) == {"channels", "playlistItems"}  # search.list는 쓰지 않는다


def test_without_a_key_rss_runs_skip_shorts_and_never_touch_the_api(data_dir, caplog):
    net = Net()  # api=None: API가 불리면 AssertionError
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1, "--only", "youtube", key=None) == 0
    assert net.calls_to(API_URL) == [] and "쇼츠 판별 건너뜀" in caplog.text
    assert not any("short" in i for i in read(data_dir, "news")["items"])


@pytest.mark.parametrize("fake_kw", [{"quota_after": 3}, {"reject_after": 3}])
def test_quota_or_key_rejection_during_collection_skips_shorts(data_dir, caplog, fake_kw):
    fake = FakeApi(**fake_kw)  # 4번째 playlistItems부터 할당량 초과/키 거부 → 남은 채널은 RSS
    with caplog.at_level("INFO"):
        assert api_run(data_dir, Net(api=fake), T1, "--only", "youtube") == 0
    assert fake.playlist_calls == 4 and shorts_calls(fake) == []  # 판별은 API를 부르지 않는다
    assert "쇼츠 판별 건너뜀" in caplog.text and not any("short" in i for i in read(data_dir, "news")["items"])


def test_a_shorts_lookup_failure_changes_nothing_for_that_channel_and_the_run_still_succeeds(data_dir, caplog):
    lize, kangji = vids_of("youtube_api_playlist_lize.json"), vids_of("youtube_api_playlist_kangji.json")
    fake = FakeApi(playlists={SH(LIZE_YT): pl(lize[0]), SH(KANGJI_YT): pl(kangji[0])},
                   fail={("playlistItems", SH(LIZE_YT)): http_error(500, b"<html>oops</html>")})
    with caplog.at_level("WARNING"):
        assert api_run(data_dir, Net(api=fake), T1, "--only", "youtube") == 0
    by = news_videos(data_dir)
    assert "short" not in by[lize[0]] and by[kangji[0]]["short"] is True  # 실패한 채널은 그대로, 다른 채널은 정상
    assert "쇼츠 판별: 아카네 리제 유튜브 조회 실패" in caplog.text
    # 다음 실행에서 복구된다
    api_run(data_dir, Net(api=FakeApi(playlists={SH(LIZE_YT): pl(lize[0])})), T2, "--only", "youtube", "--local-state")
    assert news_videos(data_dir)[lize[0]]["short"] is True


def test_only_news_runs_never_classify(data_dir):
    net = Net()
    assert api_run(data_dir, net, T1, "--only", "news") == 0
    assert net.calls_to(API_URL) == []


def test_a_failed_youtube_source_means_no_classification_even_with_a_key(data_dir):
    """첫 실행에서 판별 대기(미정) 영상이 생긴다. 다음 실행은 영상이 있는 세 채널의 업로드 목록이 모두 5xx라 YouTube 소스가 '모든 채널 실패'로
    끝난다(다른 소스 news는 성공해 실행은 계속된다). 이때는 키가 있어도 판별을 하지 않는다 — 소스가 실패한 실행이다."""
    api_run(data_dir, Net(api=FakeApi()), T1, "--only", "youtube")
    pending = [i for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-")]
    assert len(pending) == 45 and not any("short" in i for i in pending)
    boom = http_error(500, b"<html>oops</html>")
    fake = FakeApi(fail={("playlistItems", uploads_of(c)): boom for c in (LIZE_YT, KANGJI_YT, "UC2b4WRE5BZ6SIUWBeJU8rwg")})
    assert api_run(data_dir, Net(api=fake), T2, "--only", "youtube,news", "--local-state") == 0
    assert shorts_calls(fake) == []


def test_an_unexpected_shorts_error_is_logged_by_type_only_and_the_run_continues(data_dir, caplog, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError(f"내부 오류 key={KEY}")

    monkeypatch.setattr(app.shorts, "fill", boom)
    with caplog.at_level("DEBUG"):
        assert api_run(data_dir, Net(api=FakeApi()), T1, "--only", "youtube") == 0
    assert "쇼츠 판별 중 오류(RuntimeError)" in caplog.text
    assert len(news_videos(data_dir)) == 45  # 수집 결과는 그대로 저장됐다


def test_the_key_never_reaches_files_or_logs_when_a_shorts_lookup_fails(data_dir, caplog):
    leaky = requests.ConnectionError(f"boom https://x/?key={KEY}")
    with caplog.at_level("DEBUG"):
        api_run(data_dir, Net(api=FakeApi(fail={("playlistItems", SH(LIZE_YT)): leaky})), T1, "--only", "youtube", dry=False)
    assert KEY not in written_text(data_dir) and KEY not in caplog.text


def test_an_alert_for_a_known_short_is_labelled_short_and_an_undecided_one_is_not(data_dir):
    data = fx("youtube_api_playlist_lize.json")
    for n, entry in enumerate(data["items"][:2]):  # 두 영상을 방금(KST 09:30·09:31) 올라온 것으로 바꾼다 → T1(10:00) 기준 6시간 이내
        entry["contentDetails"]["videoPublishedAt"] = f"2026-10-06T00:{30 + n}:00Z"
    ids = [e["contentDetails"]["videoId"] for e in data["items"]]
    fake = FakeApi(playlists={uploads_of(LIZE_YT): data, SH(LIZE_YT): pl(ids[0])})  # ids[0]은 이미 UUSH에 있고 ids[1]은 아직 어디에도 없다
    assert api_run(data_dir, Net(api=fake), T1, "--only", "youtube", dry=False) == 0
    names = [e["author"]["name"] for m in json.loads(config.ALERTS_FILE.read_text(encoding="utf-8"))["messages"] for e in m["embeds"]]
    lize = [n for n in names if n.startswith("아카네 리제")]  # (강지의 최근 영상 알림은 이 시험과 무관하다)
    assert sorted(lize) == sorted(["아카네 리제 · 영상", "아카네 리제 · 쇼츠"])  # 쇼츠 1건 + 미정 1건(표시 없음 = '영상')
