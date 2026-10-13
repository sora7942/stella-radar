"""4기생 어비스(ABYSS) 추가 (2026-10-13). 네트워크 없음.
① members.json 값(사용자가 승인한 표) ② 태깅 ③ 데뷔 전 채널(영상 0개·재생목록 404·치지직 content:null)에서도 업데이터가 오류 없이 도는가
④ events.json의 데뷔 방송 4개. 사이트 쪽(그룹 칩·생일 없는 멤버·달력)은 test_site_logic.py."""
import json
import re

import pytest

from conftest import N_CHANNELS, ROOT
from fakeapi import FakeApi, uploads_of
from test_main import T1, Net, api_run, data_dir, read  # noqa: F401  (data_dir은 test_main의 fixture)
from updater import tagging
from updater.sources import chzzk, youtube_rss

SH = lambda cid: "UUSH" + cid[2:]  # noqa: E731
LF = lambda cid: "UULF" + cid[2:]  # noqa: E731

# 사용자가 승인한 표 (유튜브 채널 ID·치지직 ID·X: 공식 채널 PV 영상 설명 https://youtu.be/tlCeLkw8Upc, 치지직 ID는 공지 14262에도 있음)
EXPECTED = {
    "toa": ("시즈키 토아", "Shizuki Toa", "11-22", "UClcSEuDF_g_6g4snw_nAavw", "2299fad4bebb504b0978e1ec08b2f7d3", "https://x.com/ShizukiToa_", "https://www.youtube.com/@ShizukiToa", "#1FA3B5"),
    "rang": ("코가네 랑", "Cogane Rang", "08-22", "UCQ6LlsI7Bbj2yhSqLMI1gGA", "c657aa3592260a2b59669a72ec151936", "https://x.com/CoganeRang", "https://www.youtube.com/@coganerang", "#B02A6B"),
    "hiyori": ("하나요 히요리", "Hanayo Hiyori", "03-31", "UCHAr9pWGS30akL4MQCQT4uQ", "49d2c3cf8f0b2843d934ec15e82bb54c", "https://x.com/HanayoHiyori", "https://www.youtube.com/@HanayoHiyori", "#7DA82A"),
    "mary": ("토키노 메리", "Tokino Mary", "06-13", "UCGSt1yNG5l-jpYRLpJ5oNtA", "792acf9ca28b42918710327e14b06b68", "https://x.com/TokinoMary", "https://www.youtube.com/@TokinoMaryChannel", "#2B3F9E"),
}


@pytest.fixture(scope="module")
def doc():
    return json.loads((ROOT / "site" / "data" / "members.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index(doc):
    return tagging.build_index(doc)


def tags(index, text):
    return tagging.tag_text(text, index)


# ============================ members.json ===================================
def test_the_abyss_group_comes_after_cliche_and_the_four_members_are_in_debut_order(doc):
    keys = [g["key"] for g in doc["groups"]]
    assert keys == ["boss", "everys", "universe", "cliche", "abyss"]
    group = doc["groups"][-1]
    assert (group["label"], group["full"], group["en"]) == ("어비스", "4기생 어비스", "ABYSS")
    assert [k for k, m in doc["members"].items() if m["g"] == "abyss"] == ["toa", "rang", "hiyori", "mary"]  # 데뷔 순서 = 화면 순서


@pytest.mark.parametrize("key", EXPECTED)
def test_each_member_matches_the_approved_table(doc, key):
    n, en, bd, yt, chzzk_id, x, youtube, color = EXPECTED[key]
    m = doc["members"][key]
    assert (m["n"], m["en"], m["bd"], m["yt_id"], m["chzzk_id"], m["c"], m["g"]) == (n, en, bd, yt, chzzk_id, color, "abyss")
    assert m["links"] == {"youtube": youtube, "chzzk": f"https://chzzk.naver.com/{chzzk_id}", "x": x}  # 공식 홈페이지 프로필 링크는 아직 없어 생략
    assert m["official_img"] is None and m["fan"] is None and m["debut"] is None  # 모르는 값은 null


def test_ids_and_colors_are_unique_across_every_member(doc):
    ms = doc["members"].values()
    for field in ("yt_id", "chzzk_id", "c", "n", "en"):
        values = [m[field] for m in ms]
        assert len(values) == len(set(values)), field
    assert all(re.fullmatch(r"#[0-9A-F]{6}", m["c"]) for m in ms)
    assert all(re.fullmatch(r"UC[\w-]{22}", m["yt_id"]) for m in ms if m.get("yt_id"))
    assert all(re.fullmatch(r"[0-9a-f]{32}", m["chzzk_id"]) for m in ms if m.get("chzzk_id"))


def test_every_member_belongs_to_a_known_group_and_has_a_valid_birthday(doc):
    groups = {g["key"] for g in doc["groups"]}
    assert all(m["g"] in groups for m in doc["members"].values())
    assert all(re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", m["bd"]) for m in doc["members"].values())


def test_the_channel_count_includes_the_four_new_channels(doc):
    assert len(youtube_rss.channels_from_members(doc)) == N_CHANNELS == 16


# ============================ 태깅 ===========================================
@pytest.mark.parametrize("text, expected", [
    ("시즈키 토아 데뷔 방송", ["toa"]), ("토아 데뷔", ["toa"]), ("시즈키 첫 방송", ["toa"]), ("Shizuki Toa debut", ["toa"]), ("SHIZUKI TOA", ["toa"]),
    ("코가네 랑 데뷔 방송", ["rang"]), ("코가네 이야기", ["rang"]), ("Cogane Rang", ["rang"]), ("랑 데뷔", ["rang"]),
    ("하나요 히요리 자기소개", ["hiyori"]), ("히요리 방송", ["hiyori"]), ("하나요 방송", ["hiyori"]), ("Hanayo Hiyori", ["hiyori"]),
    ("토키노 메리 첫 방송", ["mary"]), ("메리 데뷔", ["mary"]), ("토키노 방송", ["mary"]), ("Tokino Mary", ["mary"]),
    ("어비스 데뷔 PV", ["abyss"]), ("ABYSS Debut PV Teaser", ["abyss"]), ("STELLIVE 4th Generation 「ABYSS」PV", ["abyss"]),
    ("4기생 데뷔", ["abyss"]), ("4기 데뷔 방송", ["abyss"]), ("4기생 어비스", ["abyss"]),
    ("시즈키 토아와 코가네 랑", ["toa", "rang"]), ("어비스 시즈키 토아 데뷔", ["abyss", "toa"]),
])
def test_abyss_names_surnames_group_and_generation_aliases(index, text, expected):
    assert tags(index, text) == expected


@pytest.mark.parametrize("text", [
    "14기 모집", "24기생", "스토아 학파", "아메리카노 마시는 방송", "메리트 있는 선택", "메리 크리스마스!", "Merry Christmas 메리크리스마스",
    "이건 어떻게 하나요?", "뭐 하고 놀까", "그 돈으로 뭐 해요", "4기통 엔진 소리",
])
def test_everyday_words_do_not_get_tagged_as_abyss_members(index, text):
    assert tags(index, text) == ["all"]


def test_the_generation_alias_only_belongs_to_abyss_and_does_not_change_other_groups(index):
    assert tags(index, "3기생 클리셰") == ["cliche"] and tags(index, "클리셰 데뷔") == ["cliche"]
    assert tags(index, "에버리스 1주년") == ["everys"] and tags(index, "리제 생일") == ["lize"]
    assert tags(index, "1기 2기 3기") == ["all"]  # 숫자 기수 줄임말은 확인된 4기만 받는다


def test_a_group_name_does_not_swallow_a_member_that_is_named_next_to_it(index):
    assert tags(index, "어비스 코가네 랑 데뷔") == ["abyss", "rang"]


def test_artist_strings_from_the_music_site_know_the_new_group(index):
    info = tagging.parse_artist("Shizuki Toa", index)
    assert (info.who, info.members, info.groups) == (["toa"], ["toa"], [])
    info = tagging.parse_artist("ABYSS", index)
    assert (info.who, info.members, info.groups) == (["abyss"], [], ["abyss"])
    info = tagging.parse_artist("Cogane Rang x Tokino Mary", index)
    assert info.who == ["rang", "mary"] and info.members == ["rang", "mary"] and info.tokens == 2
    assert tagging.parse_artist("Yuzuha Riko", index).members == ["riko"]  # 기존 멤버는 그대로


# ============================ events.json (수동 데뷔 방송 4개) ====================
def test_the_four_debut_broadcasts_are_in_events_json_with_the_announced_times():
    events = json.loads((ROOT / "site" / "data" / "events.json").read_text(encoding="utf-8"))["items"]
    debut = {e["id"]: e for e in events if e["id"].startswith("ev-abyss-debut-")}
    assert {k: (e["start"], e["who"], e["title"]) for k, e in debut.items()} == {
        "ev-abyss-debut-toa": ("2026-10-17T17:00:00+09:00", ["toa"], "시즈키 토아 데뷔 방송"),
        "ev-abyss-debut-rang": ("2026-10-17T18:00:00+09:00", ["rang"], "코가네 랑 데뷔 방송"),
        "ev-abyss-debut-hiyori": ("2026-10-18T17:00:00+09:00", ["hiyori"], "하나요 히요리 데뷔 방송"),
        "ev-abyss-debut-mary": ("2026-10-18T18:00:00+09:00", ["mary"], "토키노 메리 데뷔 방송"),
    }
    assert all(e["url"] == "https://stellive.me/news/14262" for e in debut.values())
    assert len({e["id"] for e in events}) == len(events)  # id 중복 없음


# ============================ 데뷔 전 채널에서도 업데이터가 오류 없이 돈다 ===============
ABYSS_KEYS = ("toa", "rang", "hiyori", "mary")


def abyss(data_dir):
    m = read(data_dir, "members")["members"]
    return {k: m[k] for k in ABYSS_KEYS}


def pre_debut_api(data_dir, **kw):
    """영상이 없는 채널: 업로드 재생목록·쇼츠 탭·동영상 탭이 모두 404 playlistNotFound (2026-10-13 실제 API 응답)."""
    stale = set()
    for m in abyss(data_dir).values():
        stale |= {uploads_of(m["yt_id"]), SH(m["yt_id"]), LF(m["yt_id"])}
    return FakeApi(stale=stale, **kw)


def pre_debut_net(data_dir, fake):
    return Net(api=fake, chzzk_never_streamed={m["chzzk_id"] for m in abyss(data_dir).values()})


def problems(caplog):
    """오류로 읽힐 로그: 채널·소스·쇼츠 판별·치지직 실패 경고."""
    bad = ("채널 실패", "소스", "쇼츠 판별", "치지직", "조회 실패", "찾지 못함")
    return [r.getMessage() for r in caplog.records if r.levelname in ("WARNING", "ERROR") and any(w in r.getMessage() for w in bad)]


def test_a_full_run_with_four_channels_that_have_no_videos_and_never_streamed_has_no_errors(data_dir, caplog):
    fake = pre_debut_api(data_dir)
    net = pre_debut_net(data_dir, fake)
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1) == 0
    assert problems(caplog) == [], problems(caplog)
    st = read(data_dir, "status")["members"]
    for k, m in abyss(data_dir).items():
        assert st[k]["live"] == {"on": False, "checkedAt": T1}, k  # 치지직: 방송 꺼짐으로 정상 처리
        assert "liveFails" not in st[k], k
        assert st[k]["uploads"] == uploads_of(m["yt_id"]), k  # 업로드 재생목록 ID는 캐시한다
        assert st[k].get("avatar"), k  # 아바타(채널 페이지 og:image)도 다른 멤버와 같이 수집된다
    news = read(data_dir, "news")["items"]
    assert any(i["id"].startswith("yt-") for i in news)  # 다른 채널의 영상은 그대로 들어온다
    assert not any(set(i.get("who", [])) & set(ABYSS_KEYS) for i in news if i["id"].startswith("yt-"))
    # 업로드 목록 4회 = 채널당 1회, 방금 구한 ID라서 channels.list를 또 부르지 않는다. 영상이 없어 쇼츠 판별 대상 채널도 없다
    assert fake.endpoints().count("channels") == 1
    assert not any(("playlistId=UUSH" in u or "playlistId=UULF" in u) and any(m["yt_id"][2:] in u for m in abyss(data_dir).values()) for u, _ in fake.calls)


def test_repeated_runs_stay_quiet_and_only_cost_one_channels_list_per_empty_channel(data_dir, caplog):
    api_run(data_dir, pre_debut_net(data_dir, pre_debut_api(data_dir)), T1)
    for n in range(2, 6):  # 치지직 연속 실패 경고(3회째)가 나올 만큼 돌려도 조용하다
        fake = pre_debut_api(data_dir)
        with caplog.at_level("INFO"):
            caplog.clear()
            assert api_run(data_dir, pre_debut_net(data_dir, fake), f"2026-10-06T1{n}:00:00+09:00", "--local-state") == 0
        assert problems(caplog) == [], (n, problems(caplog))
        # 캐시된 ID가 404면 낡은 캐시인지 확인하려고 그 채널만 channels.list를 한 번 더 부른다 (유닛 1) — 4채널 × 실행당 1유닛
        assert fake.endpoints().count("channels") == 4
        st = read(data_dir, "status")["members"]
        assert all("liveFails" not in st[k] and st[k]["live"]["on"] is False for k in ABYSS_KEYS)


def synthetic_playlist(video_id, title="데뷔 방송 다시보기"):
    return {"kind": "youtube#playlistItemListResponse", "items": [{
        "snippet": {"title": title, "resourceId": {"videoId": video_id}},
        "contentDetails": {"videoId": video_id, "videoPublishedAt": "2026-10-17T09:30:00Z"}}]}


def test_the_first_video_of_a_new_channel_is_collected_and_shorts_lookup_survives_404_lists(data_dir, caplog):
    """데뷔 직후: 업로드는 생겼지만 쇼츠 탭·동영상 탭 재생목록이 아직 404일 수 있다 → 오류 없이 미정으로 두었다가 24시간 뒤 일반 영상으로 확정."""
    toa = abyss(data_dir)["toa"]["yt_id"]
    fake = FakeApi(playlists={uploads_of(toa): synthetic_playlist("ABYSSVID001")}, stale={SH(toa), LF(toa)})
    with caplog.at_level("INFO"):
        assert api_run(data_dir, Net(api=fake), T1, "--only", "youtube") == 0
    item = next(i for i in read(data_dir, "news")["items"] if i["id"] == "yt-ABYSSVID001")
    assert item["who"] == ["toa"] and item["source"] == "시즈키 토아 유튜브" and "short" not in item  # 판별 전 = 필드 없음
    assert problems(caplog) == [], problems(caplog)
    own_tabs = [u for u, _ in fake.calls if (f"playlistId=UUSH{toa[2:]}" in u or f"playlistId=UULF{toa[2:]}" in u)]
    assert len(own_tabs) == 2  # 이 채널의 쇼츠 탭·동영상 탭을 한 번씩 (둘 다 404 → 영상 없음으로 본다)

    fake2 = FakeApi(playlists={uploads_of(toa): synthetic_playlist("ABYSSVID001")}, stale={SH(toa), LF(toa)})
    with caplog.at_level("INFO"):
        caplog.clear()
        assert api_run(data_dir, Net(api=fake2), "2026-10-07T10:30:00+09:00", "--only", "youtube", "--local-state") == 0
    item = next(i for i in read(data_dir, "news")["items"] if i["id"] == "yt-ABYSSVID001")
    assert item["short"] is False  # 처음 본 지 24시간이 지났고 두 탭 어디에도 없다 → 일반 영상으로 확정
    assert problems(caplog) == [], problems(caplog)


def test_a_mistyped_chzzk_id_is_still_reported_even_though_never_streamed_channels_are_fine(data_dir, caplog):
    """content:null(방송한 적 없음)만 '꺼짐'이다. 없는 채널 ID(HTTP 404)는 여전히 실패로 센다."""
    ids = {m["chzzk_id"] for m in abyss(data_dir).values()}
    bad = abyss(data_dir)["mary"]["chzzk_id"]
    net = Net(api=pre_debut_api(data_dir), chzzk_never_streamed=ids - {bad}, chzzk_fail={bad})
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1, "--only", "chzzk") == 0
    st = read(data_dir, "status")["members"]
    assert st["mary"] == {"liveFails": 1} and st["toa"]["live"] == {"on": False, "checkedAt": T1}


def test_parse_live_is_the_only_place_that_knows_about_null_content():
    assert chzzk.parse_live({"code": 200, "message": None, "content": None}, "x") == {"on": False}
