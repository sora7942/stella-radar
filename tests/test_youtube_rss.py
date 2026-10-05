import pytest
import requests

from conftest import make_response
from updater import config, tagging
from updater.sources import youtube_rss
from updater.sources.youtube_rss import Channel, FeedParseError


@pytest.fixture(scope="module")
def index(members):
    return tagging.build_index(members)


LIZE = Channel(yt_id="UC7-m6jQLinZQWIbwm9W-1iw", source="아카네 리제 유튜브", owner="lize")
OFFICIAL = Channel(yt_id="UC2b4WRE5BZ6SIUWBeJU8rwg", source="스텔라이브 공식 유튜브", owner=None)


# ============================ parse_feed =====================================
def test_member_channel_fixture(fixture_bytes, index):
    items = youtube_rss.parse_feed(fixture_bytes("youtube_rss_lize.xml"), LIZE, index)
    assert len(items) == 15
    first = items[0]
    assert first == {
        "id": "yt-p5fCRS-7u5I",
        "date": "2026-10-04T15:44:08+09:00",  # RSS는 UTC(06:44:08+00:00) → KST
        "cat": "영상",
        "who": ["lize"],
        "title": "다음 화, 야루 짤리다 [봉누도2]",
        "url": "https://www.youtube.com/watch?v=p5fCRS-7u5I",
        "source": "아카네 리제 유튜브",
        "yt": "p5fCRS-7u5I",
    }
    for it in items:
        assert it["id"] == "yt-" + it["yt"]
        assert it["date"].endswith("+09:00")
        assert "added" not in it  # added는 병합 단계에서만 정해진다


def test_member_channel_owner_wins_over_names_in_title(fixture_bytes, index):
    # 개인 채널은 제목에 다른 멤버 이름이 있어도 채널 주인만 태그한다 (SPEC 유지)
    items = youtube_rss.parse_feed(fixture_bytes("youtube_rss_official.xml"), Channel(OFFICIAL.yt_id, "린 유튜브", "rin"), index)
    assert {tuple(it["who"]) for it in items} == {("rin",)}


OFFICIAL_EXPECTED = {
    "JsnnXkxNGQU": ["everys"],  # 비바해피 … 에버리스 (EVERYS) Cover
    "yGJc0mDbCFA": ["rin", "nana"],  # 아오쿠모...나나?!
    "nuJIOZH0RXo": ["rin", "lize"],  # DAY 4 - [린, 리제 …]
    "-j3_FJ6jYPs": ["riko", "shibuki", "yuni"],  # DAY 3
    "xd5Af-zq3ME": ["mashiro", "nana", "hina"],  # DAY 2
    "n-Vs17eSiB4": ["huya", "tabi"],  # DAY 1
    "JdeMEG5qXvw": ["shibuki"],  # 부키야너는정말최고야 (별명)
    "UCWNF1dQCrk": ["all"],  # 츄~♥️♥️- [스텔라 핫클립]
    "FJWPiAKBv7s": ["all"],  # 단체 수영복 신의상 공개
}


def test_official_channel_tags_from_title(fixture_bytes, index):
    items = youtube_rss.parse_feed(fixture_bytes("youtube_rss_official.xml"), OFFICIAL, index)
    assert len(items) == 15
    by_yt = {it["yt"]: it for it in items}
    for vid, expected in OFFICIAL_EXPECTED.items():
        assert by_yt[vid]["who"] == expected, by_yt[vid]["title"]
    assert all(it["source"] == "스텔라이브 공식 유튜브" for it in items)
    assert all(it["who"] for it in items)  # 비어 있는 who는 없다 (없으면 all)


@pytest.mark.parametrize("content", [b"", b"<html><body>consent required</body></html>", b"not xml at all"])
def test_non_feed_content_is_an_error_not_an_empty_success(content, index):
    # feedparser는 이런 입력에도 예외 없이 빈 결과를 돌려주므로(bozo=False) 우리가 직접 걸러야 한다
    with pytest.raises(FeedParseError):
        youtube_rss.parse_feed(content, LIZE, index)


ATOM_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>새 채널</title></feed>'.encode("utf-8")


def test_valid_feed_with_zero_entries_is_ok(index):
    assert youtube_rss.parse_feed(ATOM_EMPTY, LIZE, index) == []


def atom(*entries: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">'
        f"<title>채널</title>{''.join(entries)}</feed>"
    ).encode("utf-8")


def test_entry_without_videoid_tag_falls_back_to_entry_id(index):
    xml = atom(
        "<entry><id>yt:video:AAAAAAAAAAA</id><title>제목</title>"
        '<link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/>'
        "<published>2026-10-04T06:44:08+00:00</published></entry>"
    )
    (it,) = youtube_rss.parse_feed(xml, LIZE, index)
    assert it["id"] == "yt-AAAAAAAAAAA" and it["yt"] == "AAAAAAAAAAA"


def test_broken_entries_are_skipped_not_fatal(index):
    xml = atom(
        "<entry><id>yt:video:BBBBBBBBBBB</id><yt:videoId>BBBBBBBBBBB</yt:videoId><title>날짜 없음</title></entry>",
        "<entry><title>id 없음</title><published>2026-10-04T06:44:08+00:00</published></entry>",
        "<entry><id>yt:video:CCCCCCCCCCC</id><yt:videoId>CCCCCCCCCCC</yt:videoId><title>정상</title>"
        "<published>2026-10-04T06:44:08+00:00</published></entry>",
    )
    items = youtube_rss.parse_feed(xml, LIZE, index)
    assert [it["yt"] for it in items] == ["CCCCCCCCCCC"]


# ============================ channels_from_members ============================
def test_channels_from_real_members(members):
    channels = youtube_rss.channels_from_members(members)
    assert len(channels) == 12  # 강지 + 멤버 10 + 공식
    assert channels[-1] == Channel(members["official"]["yt_id"], "스텔라이브 공식 유튜브", None)
    by_owner = {c.owner: c for c in channels}
    assert by_owner["kangji"].source == "강지 유튜브"
    assert by_owner["lize"] == Channel("UC7-m6jQLinZQWIbwm9W-1iw", "아카네 리제 유튜브", "lize")
    assert len({c.yt_id for c in channels}) == 12


def test_member_without_yt_id_is_skipped():
    members = {"official": {"yt_id": "UCoff"}, "members": {"a": {"n": "에이", "yt_id": "UCa"}, "b": {"n": "비", "yt_id": None}}}
    assert [c.owner for c in youtube_rss.channels_from_members(members)] == ["a", None]


# ============================ collect ========================================
def url_of(channel):
    return config.YOUTUBE_FEED_URL.format(channel_id=channel.yt_id)


class UrlGet:
    """URL별로 응답/예외를 정해 두는 get 대용."""

    def __init__(self, mapping):
        self.mapping, self.calls = mapping, []

    def __call__(self, url, **kw):
        self.calls.append(url)
        out = self.mapping[url]
        if isinstance(out, Exception):
            raise out
        return out


def test_collect_continues_after_a_channel_fails(fixture_bytes, index):
    other = Channel("UCother", "다른 채널", "rin")
    get = UrlGet(
        {
            url_of(LIZE): make_response(200, fixture_bytes("youtube_rss_lize.xml")),
            url_of(other): requests.ConnectionError("boom"),
            url_of(OFFICIAL): make_response(200, fixture_bytes("youtube_rss_official.xml")),
        }
    )
    sleeps = []
    items, errors = youtube_rss.collect([LIZE, other, OFFICIAL], index, get=get, delay=0.5, sleep=sleeps.append)
    assert len(items) == 30  # 실패한 채널만 빠진다
    assert len(errors) == 1 and "다른 채널" in errors[0] and "ConnectionError" in errors[0]
    assert sleeps == [0.5, 0.5]  # 요청 사이에만 쉰다 (첫 요청 전·마지막 뒤엔 없음)
    assert get.calls == [url_of(LIZE), url_of(other), url_of(OFFICIAL)]


def test_collect_http_error_and_bad_content_are_reported(fixture_bytes, index):
    a, b = Channel("UCa", "A", "lize"), Channel("UCb", "B", "rin")
    get = UrlGet({url_of(a): make_response(200, b"<html>blocked</html>"), url_of(b): requests.HTTPError("404", response=make_response(404))})
    items, errors = youtube_rss.collect([a, b], index, get=get, delay=0, sleep=lambda s: None)
    assert items == [] and len(errors) == 2
    assert "FeedParseError" in errors[0] and "HTTPError" in errors[1]


def test_collect_dedupes_same_video_first_channel_wins(fixture_bytes, index):
    same = make_response(200, fixture_bytes("youtube_rss_lize.xml"))
    a, b = Channel("UCa", "A 유튜브", "lize"), Channel("UCb", "B 유튜브", "rin")
    items, errors = youtube_rss.collect([a, b], index, get=UrlGet({url_of(a): same, url_of(b): same}), delay=0, sleep=lambda s: None)
    assert len(items) == 15 and errors == []
    assert all(it["source"] == "A 유튜브" and it["who"] == ["lize"] for it in items)


def test_collect_sends_no_extra_arguments_to_get_beyond_url(fixture_bytes, index):
    # timeout·User-Agent는 http.get이 강제한다 — 소스가 임의 인자를 넘기면 그 보장이 우회될 수 있다
    seen = []

    def get(url, **kw):
        seen.append(kw)
        return make_response(200, fixture_bytes("youtube_rss_lize.xml"))

    youtube_rss.collect([LIZE], index, get=get, delay=0, sleep=lambda s: None)
    assert seen == [{}]
