"""유튜브 채널 페이지 → 아바타. 전부 픽스처·가짜 응답 (네트워크 없음)."""
from datetime import timedelta

import pytest
import requests

from conftest import FakeGet, make_response
from updater import config, timeutil
from updater.sources import youtube_avatar as av

NOW_ISO = "2026-10-06T10:00:00+09:00"
NOW = timeutil.parse_kst(NOW_ISO)
YT3 = "https://yt3.googleusercontent.com/"


def page(og_image: str, *, after_head=True) -> bytes:
    """실제 페이지처럼 og:image를 </head> 뒤에 둔 최소 HTML."""
    meta = f'<meta property="og:image:width" content="900"><meta property="og:image" content="{og_image}">'
    return (f"<html><head><title>t</title></head><body>{meta}</body></html>" if after_head
            else f"<html><head>{meta}</head><body></body></html>").encode()


# ============================ 파서 ============================================
def test_parses_meta_in_head_old_layout(fixture_bytes):
    url = av.parse_avatar(fixture_bytes("youtube_channel_lize.html"))
    assert url == ("https://yt3.googleusercontent.com/Qg1w7-AfnapCDTGj9IAjAMqVA_klyc7fEfHm-7oxepHeyCXgn63aafVUWFo1gXIraLNePMYvDA"
                   "=s900-c-k-c0x00ffffff-no-rj")


def test_parses_meta_after_head_real_layout(fixture_bytes):
    html = fixture_bytes("youtube_channel_kangji.html")
    assert html.index(b"</head>") < html.index(b'property="og:image"')  # 픽스처가 실제 배치를 유지하는지 (head까지만 자르면 놓친다)
    assert av.parse_avatar(html) == (
        "https://yt3.googleusercontent.com/jRF5azs1vtU16pUJ0wzOo1I3TW9lB5jAST0IcuJYpcHgNa2KpR8LXgOVryWsaYJ8XRhpwtdq"
        "=s900-c-k-c0x00ffffff-no-rj"
    )


def test_og_image_width_and_height_are_not_mistaken_for_the_image():
    only_width = b'<html><head></head><body><meta property="og:image:width" content="900"></body></html>'
    with pytest.raises(av.AvatarParseError, match="찾지 못함"):
        av.parse_avatar(only_width)


def test_html_entities_in_the_url_are_decoded():
    assert av.parse_avatar(page(YT3 + "abc=s900&amp;x=1")) == YT3 + "abc=s900&x=1"


@pytest.mark.parametrize("bad", [
    "https://www.youtube.com/img/desktop/yt_1200.png",   # 동의·오류 페이지의 기본 이미지
    "http://yt3.googleusercontent.com/abc=s900",          # https가 아님
    "https://evilgoogleusercontent.com/abc=s900",         # 호스트 이름만 비슷함
    "https://example.com/googleusercontent.com/abc",
    "",
])
def test_rejects_images_that_are_not_youtube_profile_images(bad):
    with pytest.raises(av.AvatarParseError):
        av.parse_avatar(page(bad))


def test_accepts_ggpht_host():
    assert av.parse_avatar(page("https://yt3.ggpht.com/abc=s900")) == "https://yt3.ggpht.com/abc=s900"


@pytest.mark.parametrize("content", [b"", b"<html><head></head><body>no meta</body></html>", b"\xff\xfe\x00garbage"])
def test_pages_without_og_image_fail(content):
    with pytest.raises(av.AvatarParseError):
        av.parse_avatar(content)


# ============================ 갱신 주기 ========================================
def prev(avatar="x", checked=NOW_ISO):
    return {"avatar": avatar, "avatarCheckedAt": checked}


def test_is_due_rules():
    ago = lambda **kw: timeutil.to_kst_iso(NOW - timedelta(**kw))
    assert av.is_due({}, NOW)                                          # 처음
    assert av.is_due({"avatar": "x"}, NOW)                             # 확인 시각 없음
    assert av.is_due({"avatarCheckedAt": NOW_ISO}, NOW)                # 값이 없음 (확인했다고 쳐도 값이 없으면 다시)
    assert not av.is_due(prev(checked=ago(hours=23, minutes=59)), NOW)
    assert av.is_due(prev(checked=ago(hours=config.AVATAR_REFRESH_HOURS)), NOW)  # 정확히 24시간이면 갱신
    assert av.is_due(prev(checked=ago(days=3)), NOW)
    assert av.is_due(prev(checked="어제"), NOW)                        # 읽을 수 없는 시각
    assert not av.is_due(prev(checked=timeutil.to_kst_iso(NOW + timedelta(hours=1))), NOW)  # 미래 시각은 갱신하지 않음


# ============================ collect ========================================
MEMBERS = {
    "kangji": {"n": "강지", "yt_id": "UC_KANGJI"},
    "lize": {"n": "아카네 리제", "yt_id": "UC_LIZE"},
    "tabi": {"n": "아라하시 타비", "yt_id": "UC_TABI"},
    "noyt": {"n": "유튜브 없음"},
}


def getter(**fail):
    """채널 ID마다 고유한 og:image를 주는 가짜 get. fail={'UC_LIZE': 예외}."""
    calls = []

    def get(url, **kw):
        calls.append(url)
        cid = url.rsplit("/", 1)[1]
        if cid in fail:
            raise fail[cid]
        return make_response(200, page(f"{YT3}{cid}=s900"))

    get.calls = calls
    return get


def run(previous=None, get=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return av.collect(MEMBERS, previous or {}, now=NOW, now_iso=NOW_ISO, get=get or getter(), sleep=sleeps.append)


def test_first_run_fetches_every_member_with_a_channel():
    get = getter()
    patches, errors = run(get=get)
    assert errors == []
    assert patches == {k: {"avatar": f"{YT3}UC_{k.upper()}=s900", "avatarCheckedAt": NOW_ISO} for k in ("kangji", "lize", "tabi")}
    assert get.calls == [config.YOUTUBE_CHANNEL_URL.format(channel_id=f"UC_{k}") for k in ("KANGJI", "LIZE", "TABI")]  # yt_id 없는 멤버는 요청 없음


def test_fresh_members_are_not_requested_again():
    fresh = {k: prev(f"old-{k}") for k in ("kangji", "tabi")}
    get = getter()
    patches, errors = run(fresh, get)
    assert list(patches) == ["lize"] and errors == []
    assert get.calls == [config.YOUTUBE_CHANNEL_URL.format(channel_id="UC_LIZE")]


def test_nothing_due_means_no_requests_and_no_patches():
    get = getter()
    assert run({k: prev() for k in ("kangji", "lize", "tabi")}, get) == ({}, [])
    assert get.calls == []


def test_pauses_between_requests_but_not_before_the_first():
    sleeps = []
    run(sleeps=sleeps)
    assert sleeps == [config.REQUEST_DELAY, config.REQUEST_DELAY]  # 3번 요청 → 사이 2번
    sleeps.clear()
    run({k: prev() for k in ("kangji", "tabi")}, sleeps=sleeps)    # 1명만 요청 → 대기 없음
    assert sleeps == []


def test_one_failure_keeps_the_others_and_adds_no_patch_for_it():
    patches, errors = run(get=getter(UC_LIZE=requests.ConnectionError("boom")))
    assert set(patches) == {"kangji", "tabi"}  # lize는 패치가 없다 → 이전 avatar·avatarCheckedAt이 그대로 남는다
    assert len(errors) == 1 and "아카네 리제" in errors[0] and "ConnectionError" in errors[0]


def test_non_profile_image_counts_as_a_failure_not_a_value():
    def get(url, **kw):
        return make_response(200, page("https://www.youtube.com/img/desktop/yt_1200.png"))
    patches, errors = run(get=get)
    assert patches == {} and len(errors) == 3


def test_http_error_is_a_failure():
    get = FakeGet(make_response(500))
    patches, errors = run(get=get)
    assert patches == {} and len(errors) == 3 and all("HTTPError" in e for e in errors)
