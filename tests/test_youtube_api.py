"""YouTube Data API 수집기. 전부 실제 응답 픽스처 + 가짜 get — 네트워크 없음.
핵심 불변 조건: API 키는 URL이 아니라 X-Goog-Api-Key 헤더로만 가고, 어떤 실패에서도 로그·오류 문자열·예외에 남지 않는다."""
import inspect
import json
import logging

import pytest
import requests

from conftest import make_response
from fakeapi import KANGJI, KEY, LIZE, OFFICIAL, FakeApi, fx, http_error, uploads_of
from updater import config, http, tagging, timeutil
from updater.sources import youtube_api as api
from updater.sources.youtube_rss import Channel

CH_LIZE = Channel(LIZE, "아카네 리제 유튜브", "lize")
CH_KANGJI = Channel(KANGJI, "강지 유튜브", "kangji")
CH_OFFICIAL = Channel(OFFICIAL, "스텔라이브 공식 유튜브", None)
THREE = [CH_KANGJI, CH_LIZE, CH_OFFICIAL]


@pytest.fixture
def index(members):
    return tagging.build_index(members)


def collect(channels, index, fake, **kw):
    return api.collect(channels, index, api_key=KEY, get=fake, **kw)


def assert_no_key(*texts):
    for t in texts:
        assert KEY not in str(t), "API 키가 새어 나갔다"


# ============================ 파싱: 실제 응답 =================================
def test_lize_playlist_becomes_news_items(index):
    data = fx("youtube_api_playlist_lize.json")
    items = api.parse_playlist(data, CH_LIZE, index)
    assert len(items) == 15 == config.YOUTUBE_API_MAX_RESULTS
    first, raw = items[0], data["items"][0]
    vid = raw["contentDetails"]["videoId"]
    assert first == {
        "id": f"yt-{vid}", "date": timeutil.to_kst_iso(raw["contentDetails"]["videoPublishedAt"]), "cat": "영상", "who": ["lize"],
        "title": raw["snippet"]["title"].strip(), "url": f"https://www.youtube.com/watch?v={vid}", "source": "아카네 리제 유튜브", "yt": vid,
    }
    assert all(it["date"].endswith("+09:00") for it in items)  # UTC('Z')가 아니라 +09:00
    assert [it["date"] for it in items] == sorted((it["date"] for it in items), reverse=True)  # 응답이 최신순이고 순서를 그대로 둔다


def test_rss_and_api_items_have_the_same_shape(index, fixture_bytes):
    from updater.sources import youtube_rss
    rss = youtube_rss.parse_feed(fixture_bytes("youtube_rss_lize.xml"), CH_LIZE, index)[0]
    got = api.parse_playlist(fx("youtube_api_playlist_lize.json"), CH_LIZE, index)[0]
    assert set(rss) == set(got)  # 병합·알림·사이트가 어느 쪽에서 왔는지 신경 쓰지 않는다


def test_publish_time_is_the_videos_own_time_not_the_playlist_add_time(index):
    data = fx("youtube_api_playlist_lize.json")
    data["items"][0]["snippet"]["publishedAt"] = "2001-01-01T00:00:00Z"  # 재생목록에 '추가된' 시각이 달라도
    item = api.parse_playlist(data, CH_LIZE, index)[0]
    assert item["date"] == timeutil.to_kst_iso(data["items"][0]["contentDetails"]["videoPublishedAt"])


def test_premiere_cover_uses_the_actual_start_time_from_the_real_response(index):
    """리제의 『여우의 별자리』 커버는 프리미어: 예정 08:30:00Z, 실제 시작(=videoPublishedAt) 08:30:07Z → KST 17:30:07."""
    items = {it["yt"]: it for it in api.parse_playlist(fx("youtube_api_playlist_lize.json"), CH_LIZE, index)}
    assert items["FzefgoF26Ac"]["date"] == "2026-09-26T17:30:07+09:00"
    sample = {v["id"]: v for v in fx("youtube_api_videos_sample.json")["items"]}["FzefgoF26Ac"]
    assert sample["liveStreamingDetails"]["scheduledStartTime"] == "2026-09-26T08:30:00Z" and sample["snippet"]["liveBroadcastContent"] == "none"


def test_shorts_and_live_replays_are_ordinary_items_with_no_marker(index):
    sample = fx("youtube_api_videos_sample.json")["items"]
    shorts = [v["id"] for v in sample if "liveStreamingDetails" not in v]
    assert len(shorts) == 4 and all(v["contentDetails"]["duration"].startswith("PT") for v in sample)
    items = {it["yt"]: it for it in api.parse_playlist(fx("youtube_api_playlist_kangji.json"), CH_KANGJI, index)}
    assert set(shorts) & set(items)  # 쇼츠가 목록에 그대로 들어온다 (걸러내지 않는다)
    raw = {i["contentDetails"]["videoId"]: i for i in fx("youtube_api_playlist_kangji.json")["items"]}
    for vid in set(shorts) & set(items):
        assert sorted(raw[vid]["contentDetails"]) == ["videoId", "videoPublishedAt"]  # 응답에는 쇼츠 표시가 없다 → 구별하지 않는다


def test_official_channel_items_are_tagged_from_the_title(index):
    data = fx("youtube_api_playlist_official.json")
    items = api.parse_playlist(data, CH_OFFICIAL, index)
    assert len(items) == 15 and all(it["who"] == tagging.tag_text(it["title"], index) for it in items)
    assert any(it["who"] != ["all"] for it in items) and all(it["source"] == "스텔라이브 공식 유튜브" for it in items)


def test_private_deleted_and_broken_items_are_skipped(index, caplog):
    data = fx("youtube_api_playlist_lize.json")
    good = data["items"][0]
    private = {"snippet": {"title": "Private video", "resourceId": {"videoId": "PRIV"}}, "contentDetails": {"videoId": "PRIV"}}  # videoPublishedAt 없음
    no_title = {"snippet": {"title": "  "}, "contentDetails": {"videoId": "V1", "videoPublishedAt": "2026-10-01T00:00:00Z"}}
    bad_date = {"snippet": {"title": "t"}, "contentDetails": {"videoId": "V2", "videoPublishedAt": "어제"}}
    no_id = {"snippet": {"title": "t"}, "contentDetails": {"videoPublishedAt": "2026-10-01T00:00:00Z"}}
    with caplog.at_level("INFO"):
        items = api.parse_playlist({"items": [private, no_title, bad_date, no_id, good, {}]}, CH_LIZE, index)
    assert [it["yt"] for it in items] == [good["contentDetails"]["videoId"]]


def test_video_id_falls_back_to_resource_id(index):
    item = {"snippet": {"title": "t", "resourceId": {"videoId": "RID"}}, "contentDetails": {"videoPublishedAt": "2026-10-01T00:00:00Z"}}
    assert api.parse_playlist({"items": [item]}, CH_LIZE, index)[0]["yt"] == "RID"


@pytest.mark.parametrize("data", [{}, {"items": None}, {"items": []}])
def test_empty_responses_give_no_items(index, data):
    assert api.parse_playlist(data, CH_LIZE, index) == []


# ============================ 요청 모양: 키는 헤더로만 ==========================
def test_key_goes_in_the_header_never_the_url_and_nothing_else_is_passed(index):
    fake = FakeApi()
    collect(THREE, index, fake)
    assert len(fake.calls) == 4  # channels.list 1 + playlistItems 3
    for url, kw in fake.calls:
        assert set(kw) == {"headers"} and kw["headers"] == {"X-Goog-Api-Key": KEY} == {config.YOUTUBE_API_KEY_HEADER: KEY}
        assert KEY not in url and "key=" not in url.lower()
        assert url.startswith(config.YOUTUBE_API_URL + "/")


def test_request_parameters(index):
    fake = FakeApi()
    collect(THREE, index, fake)
    assert fake.endpoints() == ["channels", "playlistItems", "playlistItems", "playlistItems"]
    assert fake.query(0) == {"part": "contentDetails", "id": f"{KANGJI},{LIZE},{OFFICIAL}"}  # 한 번에 (maxResults는 id와 함께 못 쓴다)
    for n, ch in enumerate(THREE, 1):
        assert fake.query(n) == {"part": "snippet,contentDetails", "playlistId": uploads_of(ch.yt_id), "maxResults": "15"}


def test_default_get_is_http_get_so_timeout_and_user_agent_are_enforced():
    assert inspect.signature(api.collect).parameters["get"].default is http.get


def test_collects_items_from_all_channels_first_channel_wins_on_duplicates(index):
    same = fx("youtube_api_playlist_lize.json")
    fake = FakeApi(playlists={uploads_of(KANGJI): same, uploads_of(LIZE): same})
    res = collect([CH_KANGJI, CH_LIZE], index, fake)
    assert len(res.items) == 15 and all(it["source"] == "강지 유튜브" for it in res.items)
    assert res.errors == [] and res.remaining == [] and not res.quota_exceeded


def test_channels_list_is_chunked_at_fifty_ids():
    fake = FakeApi()
    ids = [f"UC{n:022d}" for n in range(120)]
    out = api.resolve_uploads(ids, KEY, fake)
    assert fake.endpoints() == ["channels"] * 3 and len(out) == 120 and out[ids[0]] == "UU" + ids[0][2:]
    assert [len(fake.query(n)["id"].split(",")) for n in range(3)] == [50, 50, 20]


# ============================ 업로드 재생목록 캐시 ==============================
def test_resolved_playlist_ids_are_returned_for_caching(index):
    res = collect(THREE, index, FakeApi())
    assert res.uploads == {"kangji": uploads_of(KANGJI), "lize": uploads_of(LIZE), "official": uploads_of(OFFICIAL)}  # 공식 채널은 "official"


def test_a_full_cache_skips_channels_list_entirely(index):
    fake = FakeApi()
    cached = {"kangji": uploads_of(KANGJI), "lize": uploads_of(LIZE), "official": uploads_of(OFFICIAL)}
    res = collect(THREE, index, fake, cached=cached)
    assert fake.endpoints() == ["playlistItems"] * 3 and res.uploads == {} and len(res.items) == 45


def test_only_uncached_channels_are_resolved(index):
    fake = FakeApi()
    res = collect(THREE, index, fake, cached={"kangji": uploads_of(KANGJI)})
    assert fake.query(0)["id"] == f"{LIZE},{OFFICIAL}" and res.uploads == {"lize": uploads_of(LIZE), "official": uploads_of(OFFICIAL)}


def test_a_stale_cached_id_is_re_resolved_once_and_the_cache_is_replaced(index):
    fake = FakeApi(stale={"UU_STALE_OLD_ID_"})
    res = collect([CH_LIZE], index, fake, cached={"lize": "UU_STALE_OLD_ID_"})
    assert fake.endpoints() == ["playlistItems", "channels", "playlistItems"]  # 실패 → 다시 구함 → 재시도
    assert res.uploads == {"lize": uploads_of(LIZE)} and len(res.items) == 15 and res.errors == []


def test_a_stale_id_that_resolves_to_the_same_id_is_an_error_not_a_loop(index):
    fake = FakeApi(stale={uploads_of(LIZE)})
    res = collect([CH_LIZE], index, fake, cached={"lize": uploads_of(LIZE)})
    assert fake.endpoints() == ["playlistItems", "channels"] and res.items == []
    assert res.errors == ["아카네 리제 유튜브: HTTP 404 playlistNotFound"]


def test_a_channel_missing_from_channels_list_fails_alone(index):
    res = collect(THREE, index, FakeApi(missing_channels={LIZE}))
    assert len(res.items) == 30 and res.errors == ["아카네 리제 유튜브: 업로드 재생목록을 찾지 못함"] and "lize" not in res.uploads


# ============================ 할당량 초과 → RSS 대상 ===========================
def test_quota_exceeded_on_the_first_call_hands_every_channel_to_rss(index):
    fake = FakeApi(fail={("channels", None): http_error(403, "youtube_api_error_quota.json")})
    res = collect(THREE, index, fake)
    assert res.quota_exceeded and res.remaining == THREE and res.items == [] and fake.endpoints() == ["channels"]


def test_quota_exceeded_midway_keeps_earlier_channels_and_hands_the_rest_to_rss(index):
    fake = FakeApi(quota_after=1)
    res = collect(THREE, index, fake)
    assert res.quota_exceeded and res.remaining == [CH_LIZE, CH_OFFICIAL]  # 실패한 채널부터 끝까지
    assert len(res.items) == 15 and all(it["source"] == "강지 유튜브" for it in res.items)
    assert fake.endpoints() == ["channels", "playlistItems", "playlistItems"]  # 그 뒤로는 더 부르지 않는다
    assert res.uploads  # 이미 구한 캐시는 버리지 않는다


def test_daily_limit_exceeded_counts_as_quota_too(index):
    body = {"error": {"code": 403, "errors": [{"reason": "dailyLimitExceeded"}]}}
    res = collect([CH_LIZE], index, FakeApi(fail={("channels", None): http_error(403, body)}))
    assert res.quota_exceeded


@pytest.mark.parametrize("status, body", [
    (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}),       # 일시적 속도 제한 — 키 문제도 할당량도 아니다
    (403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}),
    (400, {"error": {"errors": [{"reason": "invalidParameter"}]}}),
    (400, b"<html>bad</html>"),                                             # reason이 없는 400은 키 거부로 보지 않는다
    (404, {"error": {"errors": [{"reason": "channelNotFound"}]}}),
    (500, b"<html>oops</html>"),
    (503, {"error": {"errors": [{"reason": "backendError"}]}}),
])
def test_other_api_errors_are_channel_failures_not_a_reason_to_switch_to_rss(index, status, body):
    res = collect([CH_LIZE], index, FakeApi(fail={("channels", None): http_error(status, body)}))
    assert not res.quota_exceeded and res.key_rejected is None and res.remaining == [] and res.items == []
    assert any("재생목록" in e or "HTTP" in e for e in res.errors)


# ============================ 키 거부 → RSS 대체 ================================
@pytest.mark.parametrize("status, body, detail", [
    (400, "youtube_api_error_badkey.json", "HTTP 400 badRequest"),          # 실제 응답: 엉터리 키
    (403, "youtube_api_error_nokey.json", "HTTP 403 forbidden"),            # 실제 응답: 키 없음
    (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "HTTP 403 accessNotConfigured"),  # YouTube Data API가 꺼져 있음
    (403, {"error": {"errors": [{"reason": "ipRefererBlocked"}]}}, "HTTP 403 ipRefererBlocked"),        # 키의 IP·리퍼러 제한
    (400, {"error": {"errors": [{"reason": "keyInvalid"}]}}, "HTTP 400 keyInvalid"),
    (401, {"error": {"errors": [{"reason": "unauthorized"}]}}, "HTTP 401 unauthorized"),
    (401, b"<html>nope</html>", "HTTP 401 -"),
    (403, b"<html>blocked</html>", "HTTP 403 -"),                           # 프록시·차단 페이지처럼 reason이 없는 403
])
def test_a_rejected_key_is_classified_and_handed_to_rss(status, body, detail):
    with pytest.raises(api.KeyRejected) as ei:
        api._call(FakeApi(fail={("channels", None): http_error(status, body)}), "channels", {}, KEY)
    assert str(ei.value) == detail and not isinstance(ei.value, api.QuotaExceeded)


def test_key_rejection_on_the_first_call_hands_every_channel_to_rss(index):
    fake = FakeApi(fail={("channels", None): http_error(400, "youtube_api_error_badkey.json")})
    res = collect(THREE, index, fake)
    assert res.key_rejected == "HTTP 400 badRequest" and not res.quota_exceeded
    assert res.remaining == THREE and res.items == [] and fake.endpoints() == ["channels"]  # 더 부르지 않는다
    assert_no_key(res.key_rejected, res.errors)


def test_key_rejection_midway_keeps_earlier_channels_and_hands_the_rest_to_rss(index):
    fake = FakeApi(reject_after=1)
    res = collect(THREE, index, fake)
    assert res.key_rejected == "HTTP 403 forbidden" and res.remaining == [CH_LIZE, CH_OFFICIAL]
    assert len(res.items) == 15 and all(it["source"] == "강지 유튜브" for it in res.items)
    assert fake.endpoints() == ["channels", "playlistItems", "playlistItems"]


def test_key_rejection_while_re_resolving_a_stale_cache_is_handled_too(index):
    fake = FakeApi(stale={"UU_STALE_OLD_ID_"}, fail={("channels", None): http_error(403, "youtube_api_error_nokey.json")})
    res = collect([CH_LIZE, CH_OFFICIAL], index, fake, cached={"lize": "UU_STALE_OLD_ID_", "official": uploads_of(OFFICIAL)})
    assert res.key_rejected == "HTTP 403 forbidden" and res.remaining == [CH_LIZE, CH_OFFICIAL]


def test_quota_exceeded_is_not_reported_as_a_key_problem(index):
    res = collect(THREE, index, FakeApi(quota_after=1))
    assert res.quota_exceeded and res.key_rejected is None


# ============================ search.list는 부를 수 없다 ========================
def test_only_the_two_one_unit_endpoints_are_allowed():
    assert config.YOUTUBE_API_ENDPOINTS == ("channels", "playlistItems")  # 둘 다 호출당 1유닛


@pytest.mark.parametrize("endpoint", ["search", "videos", "activities", "commentThreads", "../search", "channels/../search"])
def test_any_other_endpoint_is_refused_before_a_request_is_sent(endpoint):
    calls = []

    def get(url, **kw):
        calls.append(url)
        raise AssertionError("요청이 나가면 안 된다")

    with pytest.raises(ValueError, match="허용되지 않은"):
        api._call(get, endpoint, {"part": "id"}, KEY)
    assert calls == []


def test_a_full_collect_only_ever_calls_the_allowed_endpoints(index):
    for fake in (FakeApi(), FakeApi(quota_after=1), FakeApi(reject_after=1), FakeApi(stale={uploads_of(LIZE)})):
        collect(THREE, index, fake, cached={"lize": uploads_of(LIZE)} if fake.stale else None)
        assert set(fake.endpoints()) <= set(config.YOUTUBE_API_ENDPOINTS)


def test_no_updater_code_references_the_search_endpoint():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in [root / "main.py", root / "send_alerts.py", *(root / "updater").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        if '"search"' in text or "'search'" in text or "/search?" in text or "youtube/v3/search" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []  # 정규식 .search() 호출은 상관없다. API 엔드포인트 문자열만 본다


# ============================ 다른 실패 · 격리 ================================
def test_one_failing_channel_does_not_stop_the_others_and_is_logged_by_name(index, caplog):
    fake = FakeApi(fail={("playlistItems", uploads_of(LIZE)): http_error(500, b"<html>oops</html>")})
    with caplog.at_level("WARNING"):
        res = collect(THREE, index, fake)
    assert len(res.items) == 30 and res.errors == ["아카네 리제 유튜브: HTTP 500 -"]
    assert [r.getMessage() for r in caplog.records if "채널 실패" in r.getMessage()] == ["유튜브 API 채널 실패 — 아카네 리제 유튜브: HTTP 500 -"]


@pytest.mark.parametrize("fixture, status, expected_type, message", [
    ("youtube_api_error_badkey.json", 400, api.KeyRejected, "HTTP 400 badRequest"),    # 실제 응답: 엉터리 키
    ("youtube_api_error_nokey.json", 403, api.KeyRejected, "HTTP 403 forbidden"),      # 실제 응답: 키 없음 — 403이어도 할당량 초과가 아니라 키 문제
    ("youtube_api_error_quota.json", 403, api.QuotaExceeded, "HTTP 403 quotaExceeded"),  # 합성
    ("youtube_api_error_playlist_not_found.json", 404, api.PlaylistNotFound, "HTTP 404 playlistNotFound"),  # 합성
])
def test_error_bodies_are_classified_by_their_reason_code(fixture, status, expected_type, message):
    fake = FakeApi(fail={("channels", None): http_error(status, fixture)})
    with pytest.raises(api.ApiError) as ei:
        api._call(fake, "channels", {"part": "x"}, KEY)
    assert type(ei.value) is expected_type and str(ei.value) == message  # 메시지는 상태와 reason뿐 (Google의 안내 문구·URL 없음)


@pytest.mark.parametrize("exc, expect", [
    (requests.ConnectionError(f"boom for url https://x/?key={KEY}"), "ConnectionError"),
    (requests.Timeout(f"slow {KEY}"), "Timeout"),
    (requests.exceptions.SSLError(f"ssl {KEY}"), "SSLError"),
])
def test_network_errors_report_only_their_type(index, exc, expect, caplog):
    with caplog.at_level("DEBUG"):
        res = collect([CH_LIZE], index, FakeApi(fail={("channels", None): exc}))
    assert any(expect in e for e in res.errors)
    assert_no_key(res.errors, caplog.text)


def test_a_non_json_success_body_is_an_error_with_no_body_text(index):
    def get(url, **kw):
        return make_response(200, f"<html>{KEY} 로그인 필요</html>")
    res = collect([CH_LIZE], index, get)
    assert res.items == [] and res.errors and all("로그인" not in e for e in res.errors)
    assert_no_key(res.errors)


def test_unexpected_exceptions_report_only_their_type_and_do_not_stop_other_channels(index, caplog):
    class Weird(Exception):
        pass
    fake = FakeApi(fail={("playlistItems", uploads_of(LIZE)): Weird(f"internal state {KEY}")})
    with caplog.at_level("DEBUG"):
        res = collect(THREE, index, fake)
    assert len(res.items) == 30 and res.errors == ["아카네 리제 유튜브: Weird"]
    assert_no_key(res.errors, caplog.text)


@pytest.mark.parametrize("failure", [
    http_error(400, "youtube_api_error_badkey.json"),           # 일반 API 오류
    http_error(403, "youtube_api_error_quota.json"),            # 할당량 초과
    http_error(404, "youtube_api_error_playlist_not_found.json"),  # 재생목록 없음
    http_error(500, b"<html>oops</html>"),                      # JSON이 아닌 오류 본문
    requests.ConnectionError(f"url?key={KEY}"),                 # 연결 오류
    requests.Timeout(f"url?key={KEY}"),
], ids=["badkey", "quota", "playlist-not-found", "html-500", "connection", "timeout"])
def test_wrapped_errors_hide_the_original_exception(failure):
    """원래 requests 예외(메시지에 URL이 있다)가 traceback에 '원인'으로 붙어 출력되지 않게 한다 — 모든 분기에서."""
    with pytest.raises(api.ApiError) as ei:
        api._call(FakeApi(fail={("channels", None): failure}), "channels", {}, KEY)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__ is True
    assert_no_key(ei.value, repr(ei.value))


def test_a_non_json_success_body_also_hides_the_original_exception():
    def get(url, **kw):
        return make_response(200, "<html>로그인</html>")
    with pytest.raises(api.ApiError) as ei:
        api._call(get, "channels", {}, KEY)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__ is True


def test_malformed_shapes_do_not_crash_the_run(index):
    bad = {uploads_of(LIZE): {"items": "문자열"}, uploads_of(KANGJI): {"items": [None, 3, {"snippet": None}]}}
    res = collect(THREE, index, FakeApi(playlists=bad))
    assert len(res.items) == 15  # 공식 채널만 정상
    assert res.errors  # 이상한 모양은 실패로 남는다 (종류만)
    assert_no_key(res.errors)


# ============================ 키 비노출 총정리 ================================
def test_no_log_line_or_error_ever_contains_the_key_across_failure_modes(index, caplog):
    scenarios = [
        FakeApi(),
        FakeApi(quota_after=1),
        FakeApi(fail={("channels", None): http_error(400, "youtube_api_error_badkey.json")}),
        FakeApi(fail={("channels", None): http_error(403, "youtube_api_error_nokey.json")}),
        FakeApi(fail={("playlistItems", uploads_of(LIZE)): http_error(500, f"서버 오류 {KEY}")}),
        FakeApi(fail={("playlistItems", uploads_of(LIZE)): requests.ConnectionError(f"{KEY}")}),
        FakeApi(stale={uploads_of(LIZE)}),
    ]
    with caplog.at_level(logging.DEBUG):
        for fake in scenarios:
            res = collect(THREE, index, fake, cached={"lize": uploads_of(LIZE)} if fake.stale else None)
            assert_no_key(res.errors, res.uploads, res.items, [r.getMessage() for r in caplog.records])
    assert_no_key(caplog.text)
