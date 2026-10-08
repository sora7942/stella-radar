"""main.py 전체 흐름을 네트워크 없이: get·data_dir·시계를 주입한다."""
import json
import shutil
from datetime import datetime

import pytest
import requests

from conftest import FIXTURES, ROOT, make_response
from fakesite import Site, song
from updater import config
import main as app

T1 = "2026-10-06T10:00:00+09:00"
T2 = "2026-10-06T10:30:00+09:00"
OFFICIAL_YT = "UC2b4WRE5BZ6SIUWBeJU8rwg"


class Clock:
    def __init__(self, iso):
        self.value = datetime.fromisoformat(iso)

    def __call__(self):
        return self.value


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(ROOT / "site" / "data", d)
    # 저장소의 catalog.json은 채워진 시드(286곡)다. 테스트는 '최초 실행·백필' 흐름을 보므로 빈 카탈로그에서 시작한다
    (d / "catalog.json").write_text(json.dumps({"updatedAt": None, "items": []}), encoding="utf-8")
    return d


def default_songs():
    return [
        song(2001, "COVER", artist="Akane Lize", date="2026-10-05", title="새 커버곡"),  # 최근 → news에도 오른다
        song(2002, "EP", artist="Yuzuha Riko", date="2026-07-24", leaf="EP", title="옛 EP"),
        song(2003, "COVER", artist="Aokumo Rin", date="2024-01-01", title="오래된 커버"),
    ]


class Net:
    """가짜 네트워크: 배포본(404), 유튜브 RSS·채널 페이지·공지(픽스처), 음악 사이트(Site), 치지직.
    live = {치지직 채널 ID: True(방송 중)}, chzzk_fail = 실패시킬 치지직 채널 ID, page_fail = 실패시킬 유튜브 채널 ID."""

    def __init__(self, *, fail_channels=(), state_status=404, songs=None, down=False, news_fails=False,
                 live=(), chzzk_fail=(), page_fail=(), open_date="2026-10-06 20:30:10", api=None, chzzk_5xx=(), chzzk_flaky=(),
                 chzzk_v2_geo_blocked=()):
        self.calls = []
        self.chzzk_5xx = set(chzzk_5xx)  # v2·v3 모두 항상 HTTP 500을 내는 치지직 채널 ID
        self.chzzk_flaky, self._flaked = set(chzzk_flaky), set()  # 첫 요청만 HTTP 500이고 다음 요청부터 정상인 채널 ID
        self.chzzk_v2_geo_blocked = set(chzzk_v2_geo_blocked)  # v2만 HTTP 500 code 9004(해외 시청 불가)이고 v3는 정상인 채널 ID
        self.api = api  # fakeapi.FakeApi. None이면 YouTube API 호출이 오면 실패시킨다 (키가 없을 땐 API를 부르면 안 된다)
        self.fail_channels, self.state_status, self.down, self.news_fails = set(fail_channels), state_status, down, news_fails
        self.live, self.chzzk_fail, self.page_fail = set(live), set(chzzk_fail), set(page_fail)
        self.open_date = open_date  # 방송 중인 멤버의 openDate (치지직은 오프셋 없는 KST 문자열). None이면 값이 없는 응답
        self.site = Site(default_songs() if songs is None else songs)

    def __call__(self, url, **kw):
        self.calls.append(url)
        if "/data/" in url:  # 이전 상태(배포본)
            status = self.state_status.get(url.split("/data/")[1].split(".json")[0], 404) if isinstance(self.state_status, dict) else self.state_status
            resp = make_response(status, "")
            raise requests.HTTPError(str(status), response=resp)
        if self.down:
            raise requests.ConnectionError("down")
        if "feeds/videos.xml" in url:
            cid = url.split("channel_id=")[1]
            if cid in self.fail_channels:
                raise requests.ConnectionError("down")
            name = "youtube_rss_official.xml" if cid == OFFICIAL_YT else "youtube_rss_lize.xml"
            return make_response(200, (FIXTURES / name).read_bytes())
        if url == config.NEWS_URL:
            if self.news_fails:
                raise requests.HTTPError("503", response=make_response(503))
            return make_response(200, (FIXTURES / "stellive_news_list.html").read_bytes())
        if url.startswith("https://stellive.me/music"):
            return self.site(url)
        if url.startswith(config.YOUTUBE_API_URL):
            if self.api is None:
                raise AssertionError(f"API 키가 없는데 YouTube API를 불렀다: {url}")
            return self.api(url, **kw)
        if url.startswith("https://www.youtube.com/channel/"):  # 채널 페이지: og:image가 </head> 뒤에 있는 실제 배치
            cid = url.rsplit("/", 1)[1]
            if cid in self.page_fail:
                raise requests.ConnectionError("down")
            og = f'<meta property="og:image" content="https://yt3.googleusercontent.com/{cid}=s900-c-k-c0x00ffffff-no-rj">'
            return make_response(200, f"<html><head><title>t</title></head><body>{og}</body></html>")
        if url.startswith(("https://api.chzzk.naver.com/polling/v2/channels/", "https://api.chzzk.naver.com/polling/v3/channels/")):
            cid = url.split("/channels/")[1].split("/")[0]
            if cid in self.chzzk_fail:
                raise requests.ConnectionError("blocked")
            if "/polling/v2/" in url and cid in self.chzzk_v2_geo_blocked:  # 후야 사례: v2만 HTTP 500 code 9004(해외 시청 불가), v3는 정상
                raise requests.HTTPError("500 Server Error", response=make_response(500, json.dumps({"code": 9004, "message": "해외 시청 불가능한 컨텐츠 입니다.", "content": None})))
            if cid in self.chzzk_5xx or (cid in self.chzzk_flaky and cid not in self._flaked):
                self._flaked.add(cid)
                raise requests.HTTPError("500 Server Error", response=make_response(500))
            d = json.loads((FIXTURES / ("chzzk_live_open.json" if cid in self.live else "chzzk_live_close.json")).read_text(encoding="utf-8"))
            d["content"]["channelId"] = cid
            if cid in self.live:
                d["content"]["openDate"] = self.open_date
            return make_response(200, json.dumps(d))
        raise AssertionError(f"예상 밖의 URL: {url}")

    def calls_to(self, prefix):
        return [c for c in self.calls if c.startswith(prefix)]


def run(data_dir, net, clock=T1, *extra):
    return app.main(["--dry-run", *extra], get=net, data_dir=data_dir, now=Clock(clock), sleep=lambda s: None)


def read(data_dir, name):
    return json.loads((data_dir / f"{name}.json").read_text(encoding="utf-8"))


# ============================ 전체 실행 =======================================
def test_first_run_collects_all_sources_and_keeps_seeds(data_dir):
    seeds = read(data_dir, "news")["items"]
    assert run(data_dir, Net()) == 0

    news = read(data_dir, "news")
    assert news["updatedAt"] == T1
    by_id = {it["id"]: it for it in news["items"]}
    for s in seeds:
        assert by_id[s["id"]] == s  # 시드 18개는 한 글자도 안 바뀐다 (같은 id의 공지가 수집돼도 기존 항목이 이김)

    videos = [it for it in news["items"] if it["id"].startswith("yt-")]
    assert videos and all(v["added"] == T1 and v["date"].endswith("+09:00") for v in videos)
    assert by_id["sl-14044"]["added"] == T1 and by_id["sl-14044"]["date"] == "2026-10-05"  # 시드에 없던 신규 공지
    assert by_id["mu-2001"]["title"] == "새 커버곡" and by_id["mu-2001"]["yt"]  # 최근 곡만 news에도
    assert "mu-2002" not in by_id and "mu-2003" not in by_id

    catalog = read(data_dir, "catalog")
    assert catalog["updatedAt"] == T1
    assert {c["id"] for c in catalog["items"]} == {"2001", "2002", "2003"}
    assert [c["id"] for c in catalog["items"]] == ["2001", "2002", "2003"]  # 날짜 내림차순


def test_second_run_only_moves_updated_at(data_dir):
    run(data_dir, Net(), T1)
    first_news, first_catalog = read(data_dir, "news"), read(data_dir, "catalog")
    net = Net()
    run(data_dir, net, T2, "--local-state")
    assert read(data_dir, "news")["updatedAt"] == T2 and read(data_dir, "catalog")["updatedAt"] == T2
    assert read(data_dir, "news")["items"] == first_news["items"]  # added 포함 불변
    assert read(data_dir, "catalog")["items"] == first_catalog["items"]
    # 새 곡이 없으니 음악 사이트에는 목록만 요청한다 (탭·상세 0회)
    assert net.calls_to("https://stellive.me/music") == [config.MUSIC_URL]


def test_uses_deployed_state_first_then_local_only_on_404(data_dir):
    net = Net()
    run(data_dir, net)
    assert all(any(f"/data/{n}.json?t=" in u for u in net.calls) for n in ("news", "catalog", "status"))
    net2 = Net()
    run(data_dir, net2, T2, "--local-state")
    assert not any("/data/" in u for u in net2.calls)


def test_output_files_are_utf8_without_ascii_escapes(data_dir):
    run(data_dir, Net())
    for name in ("news", "catalog"):
        text = (data_dir / f"{name}.json").read_text(encoding="utf-8")
        assert "\\u" not in text and "새 커버곡" in text  # news에는 mu-2001, catalog에는 2001로 들어 있다


# ============================ 소스 실패 격리 ===================================
def test_one_failed_channel_does_not_stop_the_run(data_dir):
    assert run(data_dir, Net(fail_channels={"UC7-m6jQLinZQWIbwm9W-1iw"})) == 0
    assert any(it["id"].startswith("yt-") for it in read(data_dir, "news")["items"])


def test_failed_channel_is_logged_and_the_others_are_still_collected(data_dir, caplog):
    kangji_yt = people(data_dir)[0]["kangji"]["yt_id"]  # 첫 채널. 실패하면 다음 채널이 같은 (가짜) 피드를 받아 항목을 가져간다
    with caplog.at_level("INFO"):
        assert run(data_dir, Net(fail_channels={kangji_yt})) == 0
    sources = {it["source"] for it in read(data_dir, "news")["items"] if it["id"].startswith("yt-")}
    assert "강지 유튜브" not in sources and "아야츠노 유니 유튜브" in sources and "스텔라이브 공식 유튜브" in sources
    failed = [r.getMessage() for r in caplog.records if "유튜브 채널 실패" in r.getMessage()]
    assert len(failed) == 1 and "강지 유튜브" in failed[0]  # 어느 채널이 왜 실패했는지 로그에 남는다
    assert "일부 실패 1건" in caplog.text


def test_news_source_failure_keeps_the_others(data_dir):
    assert run(data_dir, Net(news_fails=True)) == 0
    items = read(data_dir, "news")["items"]
    assert any(i["id"].startswith("yt-") for i in items) and "sl-14044" not in {i["id"] for i in items}
    assert (data_dir / "catalog.json").exists() and read(data_dir, "catalog")["items"]


def test_music_failure_leaves_catalog_untouched_and_other_sources_continue(data_dir):
    before = (data_dir / "catalog.json").read_bytes()
    net = Net(songs=[song(1, "SINGLE", leaf="하위"), song(2, "SINGLE", leaf="하위"), song(3, "SINGLE", leaf="하위")])
    net.site.page_size = 1
    net.site.fail["https://stellive.me/music/category/278?page=2"] = requests.ConnectionError("boom")  # 분류 탭을 끝까지 못 읽는다
    assert run(data_dir, net) == 0
    assert (data_dir / "catalog.json").read_bytes() == before  # 추측해서 분류하지 않고, catalog는 그대로
    assert not net.site.detail_calls()  # 상세는 받지도 않았다
    news = read(data_dir, "news")
    assert news["updatedAt"] == T1 and any(i["id"].startswith("yt-") for i in news["items"])  # 나머지는 정상 반영


def test_all_sources_failing_exits_1_and_writes_nothing(data_dir):
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")}
    assert run(data_dir, Net(down=True)) == 1
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")} == before


@pytest.mark.parametrize("status", [500, 503, 403])
def test_unreadable_previous_state_exits_1_and_writes_nothing(data_dir, status):
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")}
    assert run(data_dir, Net(state_status=status)) == 1  # 시드로 되돌아가서 덮어쓰지 않는다
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")} == before


def test_unreadable_catalog_state_alone_also_aborts(data_dir):
    before = (data_dir / "news.json").read_bytes()
    assert run(data_dir, Net(state_status={"news": 404, "catalog": 500}), T1, "--only", "music") == 1
    assert (data_dir / "news.json").read_bytes() == before


# ============================ --only ==========================================
def test_unknown_source_is_an_argument_error(data_dir, capsys):
    with pytest.raises(SystemExit) as ei:
        app.main(["--only", "nope"], get=Net(), data_dir=data_dir)
    assert ei.value.code == 2 and "nope" in capsys.readouterr().err


def test_only_news_never_touches_music_or_catalog(data_dir):
    catalog_before = (data_dir / "catalog.json").read_bytes()
    net = Net()
    assert run(data_dir, net, T1, "--only", "news") == 0
    assert net.calls_to("https://stellive.me/music") == [] and not any("catalog.json" in c for c in net.calls)
    assert (data_dir / "catalog.json").read_bytes() == catalog_before
    assert any(i["id"] == "sl-14044" for i in read(data_dir, "news")["items"])


def test_only_music_writes_catalog_and_recent_news_only(data_dir):
    net = Net()
    assert run(data_dir, net, T1, "--only", "music") == 0
    assert net.calls_to("https://www.youtube.com") == [] and config.NEWS_URL not in net.calls
    assert {c["id"] for c in read(data_dir, "catalog")["items"]} == {"2001", "2002", "2003"}
    assert {i["id"] for i in read(data_dir, "news")["items"] if i["id"].startswith("mu-")} >= {"mu-2001"}


def test_sources_run_in_fixed_order_regardless_of_only_order(data_dir):
    net = Net()
    run(data_dir, net, T1, "--only", "music,youtube,news")
    first_of = lambda needle: next(i for i, c in enumerate(net.calls) if needle in c and "/data/" not in c)
    assert first_of("feeds/videos.xml") < first_of("stellive.me/news") < first_of("stellive.me/music")


def test_pauses_between_sources(data_dir):
    sleeps = []
    app.main(["--dry-run", "--only", "youtube,news"], get=Net(), data_dir=data_dir, now=Clock(T1), sleep=sleeps.append)
    assert config.REQUEST_DELAY in sleeps  # 소스 사이 간격


# ============================ 백필 (40곡씩) =====================================
def test_backfill_over_several_runs_without_flooding_the_feed(data_dir):
    songs = [song(n, "COVER", date="2024-05-01") for n in range(1, 101)]  # 전부 옛날 곡 100곡
    net = Net(songs=songs)
    seed_music = {i["id"] for i in read(data_dir, "news")["items"] if i["id"].startswith("mu-")}  # 시드에 이미 있는 음악 소식
    sizes = []
    for i, clock in enumerate(("2026-10-06T10:00:00+09:00", "2026-10-06T10:30:00+09:00", "2026-10-06T11:00:00+09:00")):
        assert run(data_dir, net, clock, "--only", "music", "--local-state") == 0
        sizes.append(len(read(data_dir, "catalog")["items"]))
    assert sizes == [40, 80, 100]  # 실행당 40곡
    after = {i["id"] for i in read(data_dir, "news")["items"] if i["id"].startswith("mu-")}
    assert seed_music and after == seed_music  # 옛 커버곡 100곡은 피드에 하나도 오르지 않는다 (시드 외 새 mu- 없음)
    assert len(net.site.detail_calls()) == 100  # 한 곡도 두 번 받지 않았다


def test_backfill_run_two_does_not_treat_old_songs_as_new(data_dir):
    songs = [song(n, "COVER", date="2024-05-01") for n in range(1, 81)]
    net = Net(songs=songs)
    run(data_dir, net, T1, "--only", "music", "--local-state")
    news_after_first = read(data_dir, "news")["items"]
    run(data_dir, net, T2, "--only", "music", "--local-state")  # catalog가 비어 있지 않은 2회차 — SPEC 7장 규칙이 깨지던 지점
    assert read(data_dir, "news")["items"] == news_after_first


# ============================ 비밀·출력 ========================================
def test_output_contains_no_webhook_text_and_real_data_is_untouched(data_dir, capsys, monkeypatch, caplog):
    real_before = {n: (config.DATA_DIR / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")}
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/SECRET-ID/SECRET-TOKEN")
    with caplog.at_level("DEBUG"):
        run(data_dir, Net())
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err + caplog.text
    assert {n: (config.DATA_DIR / f"{n}.json").read_bytes() for n in ("news", "catalog", "status")} == real_before  # 테스트는 tmp에만 쓴다


# ============================ 아바타·방송 상태 (status.json) =======================
T3 = "2026-10-07T11:00:00+09:00"  # T1보다 25시간 뒤 → 아바타 갱신 주기(24시간)를 지났다
T4 = "2026-10-07T11:30:00+09:00"
AV_SUFFIX = "=s240-c-k-c0x00ffffff-no-rj"  # 가짜 채널 페이지는 =s900을 주지만 저장은 =s240


def people(data_dir):
    m = read(data_dir, "members")["members"]
    return m, [k for k, v in m.items() if v.get("yt_id")], {k: v["chzzk_id"] for k, v in m.items() if v.get("chzzk_id")}


def test_status_first_run_has_avatars_and_live_for_those_with_ids(data_dir):
    m, with_yt, chzzk_ids = people(data_dir)
    assert run(data_dir, Net()) == 0
    st = read(data_dir, "status")
    assert st["updatedAt"] == T1 and set(st["members"]) == set(with_yt)
    for k in with_yt:
        assert st["members"][k]["avatar"] == f"https://yt3.googleusercontent.com/{m[k]['yt_id']}{AV_SUFFIX}"  # 자기 채널의 이미지
        assert st["members"][k]["avatarCheckedAt"] == T1
        assert ("live" in st["members"][k]) == (k in chzzk_ids)  # chzzk_id가 없는 멤버는 live를 만들어 내지 않는다
        assert st["members"][k].get("live", {"on": False, "checkedAt": T1}) == {"on": False, "checkedAt": T1}  # 확인 시각은 이번 실행 시각
    assert "kangji" in chzzk_ids and "live" in st["members"]["kangji"]  # 강지도 이제 치지직을 확인한다
    assert "https://www.youtube.com/channel/" not in json.dumps(st)  # 이미지는 링크만 저장한다 (페이지 URL이 아님)


def test_chzzk_is_requested_only_for_members_with_an_id(data_dir):
    _, _, chzzk_ids = people(data_dir)
    net = Net()
    run(data_dir, net)
    assert sorted(net.calls_to("https://api.chzzk.naver.com")) == sorted(
        config.CHZZK_LIVE_STATUS_URL.format(channel_id=i) for i in chzzk_ids.values())


def test_live_on_is_recorded_with_title_url_and_since(data_dir):
    _, _, chzzk_ids = people(data_dir)
    run(data_dir, Net(live={chzzk_ids["lize"]}))
    live = read(data_dir, "status")["members"]["lize"]["live"]
    assert live["on"] is True and live["title"] == "합성 방송 제목 (테스트용)"
    assert live["url"] == f"https://chzzk.naver.com/live/{chzzk_ids['lize']}" and live["since"] == "2026-10-06T20:30:10+09:00"
    assert live["checkedAt"] == T1


def test_second_run_within_a_day_skips_avatar_pages_but_repolls_live(data_dir):
    _, _, chzzk_ids = people(data_dir)
    run(data_dir, Net(), T1)
    net = Net(live={chzzk_ids["lize"]})
    run(data_dir, net, T2, "--local-state")
    assert net.calls_to("https://www.youtube.com/channel/") == []  # 24시간 이내라 채널 페이지는 요청하지 않는다
    st = read(data_dir, "status")
    assert st["updatedAt"] == T2
    assert st["members"]["lize"]["avatarCheckedAt"] == T1 and st["members"]["lize"]["live"]["on"] is True


def test_after_a_day_avatars_are_read_again(data_dir):
    _, with_yt, _ = people(data_dir)
    run(data_dir, Net(), T1)
    net = Net()
    run(data_dir, net, T3, "--local-state")
    assert len(net.calls_to("https://www.youtube.com/channel/")) == len(with_yt)
    assert all(e["avatarCheckedAt"] == T3 for e in read(data_dir, "status")["members"].values())


def test_failed_avatar_page_keeps_the_old_value_and_is_retried_next_run(data_dir):
    m, _, _ = people(data_dir)
    run(data_dir, Net(), T1)
    old = read(data_dir, "status")["members"]["lize"]["avatar"]
    run(data_dir, Net(page_fail={m["lize"]["yt_id"]}), T3, "--local-state")
    st = read(data_dir, "status")["members"]
    assert st["lize"]["avatar"] == old and st["lize"]["avatarCheckedAt"] == T1  # 이전 값 유지, 확인 시각도 그대로
    assert st["tabi"]["avatarCheckedAt"] == T3  # 다른 멤버는 정상 갱신
    net = Net()
    run(data_dir, net, T4, "--local-state")  # 확인 시각이 그대로라 다음 실행에 다시 시도한다
    assert net.calls_to("https://www.youtube.com/channel/") == [config.YOUTUBE_CHANNEL_URL.format(channel_id=m["lize"]["yt_id"])]
    assert read(data_dir, "status")["members"]["lize"]["avatarCheckedAt"] == T4


def test_failed_live_request_does_not_turn_a_live_member_off(data_dir):
    _, _, chzzk_ids = people(data_dir)
    run(data_dir, Net(live={chzzk_ids["lize"]}), T1)
    first = read(data_dir, "status")["members"]["lize"]["live"]
    run(data_dir, Net(chzzk_fail={chzzk_ids["lize"]}), T2, "--local-state")
    st = read(data_dir, "status")["members"]
    assert st["lize"]["live"] == first and first["checkedAt"] == T1  # 실패는 꺼짐이 아니다 (다음 성공 때 가짜 off→on 알림이 나지 않게). 확인 시각도 옛 값 그대로 → 사이트가 2시간 뒤 숨긴다
    assert st["tabi"]["live"] == {"on": False, "checkedAt": T2}  # 나머지는 정상 반영
    run(data_dir, Net(), T3, "--local-state")  # 복구 후 실제로 꺼졌으면 off
    assert read(data_dir, "status")["members"]["lize"]["live"] == {"on": False, "checkedAt": T3}


def test_all_chzzk_requests_failing_is_a_source_failure_that_keeps_every_live_value(data_dir, caplog):
    _, _, chzzk_ids = people(data_dir)
    run(data_dir, Net(live={chzzk_ids["lize"]}), T1)
    with caplog.at_level("ERROR"):
        assert run(data_dir, Net(chzzk_fail=set(chzzk_ids.values())), T2, "--local-state") == 0  # 소스 하나의 실패는 실행을 멈추지 않는다
    assert "소스 chzzk 실패" in caplog.text
    st = read(data_dir, "status")
    assert st["members"]["lize"]["live"]["on"] is True and st["updatedAt"] == T2  # 아바타는 정상이라 파일은 갱신된다
    assert st["members"]["lize"]["live"]["checkedAt"] == T1  # 계속 실패하면 확인 시각이 멈춘다 → 사이트가 2시간 뒤 이 LIVE를 숨긴다
    assert all(st["members"][k]["liveFails"] == 1 for k in chzzk_ids)  # 전부 실패한 실행도 연속 실패 횟수는 남긴다 (차단이 길어지면 경고가 나오게)


def test_only_chzzk_with_every_request_failing_still_exits_1_and_writes_nothing(data_dir):
    _, _, chzzk_ids = people(data_dir)
    run(data_dir, Net(live={chzzk_ids["lize"]}), T1, "--only", "chzzk")
    before = (data_dir / "status.json").read_bytes()
    assert run(data_dir, Net(chzzk_fail=set(chzzk_ids.values())), T2, "--only", "chzzk", "--local-state") == 1  # 성공한 소스가 하나도 없다
    assert (data_dir / "status.json").read_bytes() == before


def test_a_5xx_falls_back_to_the_next_endpoint_inside_a_run_and_leaves_no_failure_count(data_dir):
    _, _, chzzk_ids = people(data_dir)
    lize = chzzk_ids["lize"]
    net = Net(live={lize}, chzzk_flaky={lize})
    assert run(data_dir, net, T1, "--only", "chzzk") == 0
    v2, v3 = (u.format(channel_id=lize) for u in config.CHZZK_LIVE_STATUS_URLS)
    assert net.calls_to("https://api.chzzk.naver.com") .count(v2) == 1 and net.calls_to("https://api.chzzk.naver.com").count(v3) == 1
    entry = read(data_dir, "status")["members"]["lize"]
    assert entry["live"]["on"] is True and entry["live"]["checkedAt"] == T1 and "liveFails" not in entry


def test_a_member_geo_blocked_on_v2_is_read_from_v3_and_the_others_cost_no_extra_requests(data_dir, caplog, capsys):
    """후야 사례(Actions에서 v2만 HTTP 500 code 9004): v3로 상태를 읽어 LIVE 표시와 방송 시작 알림이 정상으로 나온다."""
    _, _, chzzk_ids = people(data_dir)
    huya = chzzk_ids["huya"]
    net = Net(live={huya}, chzzk_v2_geo_blocked={huya})
    with caplog.at_level("INFO"):
        assert run(data_dir, net, T1, "--only", "chzzk") == 0
    chzzk_calls = net.calls_to("https://api.chzzk.naver.com")
    assert len(chzzk_calls) == len(chzzk_ids) + 1  # 11명 × v2 한 번 + 후야 v3 한 번
    assert [c for c in chzzk_calls if "/polling/v3/" in c] == [config.CHZZK_LIVE_STATUS_URLS[1].format(channel_id=huya)]
    entry = read(data_dir, "status")["members"]["huya"]
    assert entry["live"]["on"] is True and entry["live"]["checkedAt"] == T1 and entry["live"]["since"] == "2026-10-06T20:30:10+09:00" and "liveFails" not in entry
    assert "치지직 사키하네 후야: HTTP 500 (code 9004) — 다음 엔드포인트 시도" in caplog.text
    assert "사키하네 후야 · 방송 시작" in capsys.readouterr().out  # 방송 시작 알림도 정상으로 나온다 (dry-run 출력)


def chzzk_run(data_dir, net, clock, *, actions):
    return api_run(data_dir, net, clock, "--only", "chzzk", "--local-state", key=None, actions=actions)


def test_the_same_member_failing_three_runs_in_a_row_warns_on_the_third_and_recovery_clears_it(data_dir, capsys, caplog):
    _, _, chzzk_ids = people(data_dir)
    lize = chzzk_ids["lize"]
    stuck = lambda: Net(live={lize}, chzzk_5xx={lize})
    run(data_dir, Net(live={lize}), T1, "--only", "chzzk")  # 방송 중으로 시작
    first_live = read(data_dir, "status")["members"]["lize"]["live"]
    counts, annotations = [], []
    with caplog.at_level("WARNING"):
        for clock in ("2026-10-06T10:30:00+09:00", "2026-10-06T11:00:00+09:00", "2026-10-06T11:30:00+09:00", "2026-10-06T12:00:00+09:00"):
            assert chzzk_run(data_dir, stuck(), clock, actions=True) == 0
            entry = read(data_dir, "status")["members"]["lize"]
            counts.append(entry["liveFails"])
            assert entry["live"] == first_live  # 실패하는 동안 이전 live·checkedAt은 그대로 (사이트가 2시간 뒤 숨긴다)
            annotations.append([l for l in capsys.readouterr().out.splitlines() if l.startswith("::warning")])
    assert counts == [1, 2, 3, 4]
    assert annotations[0] == [] and annotations[1] == []  # 2회째까지는 조용하다
    for lines in annotations[2:]:  # 3회째부터 연속되는 동안 매 실행
        assert len(lines) == 1 and lines[0].startswith("::warning title=치지직::") and "아카네 리제" in lines[0] and "HTTP 500" in lines[0]
        assert "api.chzzk.naver.com" not in lines[0] and lize not in lines[0]  # URL·채널 ID는 주석에 넣지 않는다
    assert "3회 연속 실패" in caplog.text
    chzzk_run(data_dir, Net(live=set()), "2026-10-06T12:30:00+09:00", actions=True)  # 복구
    entry = read(data_dir, "status")["members"]["lize"]
    assert "liveFails" not in entry and entry["live"] == {"on": False, "checkedAt": "2026-10-06T12:30:00+09:00"}
    assert not [l for l in capsys.readouterr().out.splitlines() if l.startswith("::warning")]


def test_the_streak_warning_is_only_a_log_line_outside_github_actions(data_dir, capsys, caplog):
    _, _, chzzk_ids = people(data_dir)
    lize = chzzk_ids["lize"]
    run(data_dir, Net(), T1, "--only", "chzzk")
    with caplog.at_level("WARNING"):
        for clock in ("2026-10-06T10:30:00+09:00", "2026-10-06T11:00:00+09:00", "2026-10-06T11:30:00+09:00"):
            chzzk_run(data_dir, Net(chzzk_5xx={lize}), clock, actions=False)
    assert read(data_dir, "status")["members"]["lize"]["liveFails"] == 3
    assert "::warning" not in capsys.readouterr().out and "3회 연속 실패 (HTTP 500)" in caplog.text


def test_one_members_failure_does_not_affect_another_member_in_the_same_run(data_dir):
    _, _, chzzk_ids = people(data_dir)
    lize, tabi = chzzk_ids["lize"], chzzk_ids["tabi"]
    run(data_dir, Net(live={lize}), T1, "--only", "chzzk")
    run(data_dir, Net(live={lize, tabi}, chzzk_5xx={lize}), T2, "--only", "chzzk", "--local-state")
    st = read(data_dir, "status")["members"]
    assert st["tabi"]["live"]["on"] is True and "liveFails" not in st["tabi"]  # 다른 멤버는 정상 갱신
    assert st["lize"]["liveFails"] == 1 and st["lize"]["live"]["checkedAt"] == T1


def test_only_avatar_and_chzzk_leave_other_data_alone(data_dir):
    catalog_before = (data_dir / "catalog.json").read_bytes()
    items_before = read(data_dir, "news")["items"]
    net = Net()
    assert run(data_dir, net, T1, "--only", "chzzk,avatar") == 0
    assert (data_dir / "catalog.json").read_bytes() == catalog_before and read(data_dir, "news")["items"] == items_before
    assert net.calls_to("https://www.youtube.com/feeds") == [] and net.calls_to("https://stellive.me") == []
    assert read(data_dir, "status")["members"]


def test_sources_without_status_do_not_load_or_write_it(data_dir):
    before = (data_dir / "status.json").read_bytes()
    net = Net()
    run(data_dir, net, T1, "--only", "news")
    assert not any("status.json" in c for c in net.calls) and (data_dir / "status.json").read_bytes() == before


def test_disabled_source_is_skipped_by_default_but_still_runnable_with_only(data_dir, monkeypatch):
    monkeypatch.setattr(config, "ENABLED_SOURCES", tuple(s for s in config.ENABLED_SOURCES if s != "chzzk"))
    net = Net()
    run(data_dir, net)
    assert net.calls_to("https://api.chzzk.naver.com") == [] and net.calls_to("https://www.youtube.com/channel/")
    assert all("live" not in e for e in read(data_dir, "status")["members"].values())
    lize_id = people(data_dir)[2]["lize"]
    net2 = Net(live={lize_id})
    run(data_dir, net2, T2, "--only", "chzzk", "--local-state")  # --only로는 꺼진 소스도 돌릴 수 있다
    assert net2.calls_to("https://api.chzzk.naver.com")
    assert read(data_dir, "status")["members"]["lize"]["live"]["checkedAt"] == T2
    run(data_dir, Net(), T3, "--local-state")  # 이후 기본 실행은 치지직을 안 돌린다 → 확인 시각은 T2에서 멈추고, 사이트가 2시간 뒤 숨긴다
    live = read(data_dir, "status")["members"]["lize"]["live"]
    assert live["on"] is True and live["checkedAt"] == T2


def test_unreadable_status_state_aborts_when_a_status_source_runs(data_dir):
    before = (data_dir / "news.json").read_bytes()
    assert run(data_dir, Net(state_status={"news": 404, "catalog": 404, "status": 500}), T1, "--only", "avatar") == 1
    assert (data_dir / "news.json").read_bytes() == before


# ============================ 알림: main은 파일만 남긴다 ========================
# 알림은 배포가 성공한 뒤에 나가야 하므로 main.py는 디스코드로 보내지 않고 config.ALERTS_FILE에 보낼 내용을 남긴다 (발송: send_alerts.py).
HOOK = "https://discord.com/api/webhooks/123456789/SECRET-TOKEN-abcdef"
LIZE_CLOSE_TO_VIDEOS = "2026-10-04T16:30:00+09:00"  # 리제 픽스처의 최신 영상(10-04 15:44 KST)보다 46분 뒤


def pending(alerts_file=None):
    """알림 파일의 내용(없으면 None)."""
    path = alerts_file or config.ALERTS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def pending_embeds():
    doc = pending()
    return [e for m in doc["messages"] for e in m["embeds"]] if doc else []


def save_run(data_dir, net, clock, *extra):
    """--dry-run 없이 실행 (알림 파일을 남기는 실제 경로). 디스코드는 건드리지 않는다."""
    return app.main([*extra], get=net, data_dir=data_dir, now=Clock(clock), sleep=lambda s: None)


def test_real_run_leaves_the_alerts_in_a_file_and_sends_nothing(data_dir, monkeypatch, capsys, caplog):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)  # 있어도 main.py는 보지도 않는다
    net = Net()
    with caplog.at_level("DEBUG"):
        assert save_run(data_dir, net, T1) == 0
    doc = pending()
    assert doc["createdAt"] == T1 and doc["alertCount"] >= 1 and doc["messages"]
    assert "새 커버곡" in {e["title"] for e in pending_embeds()}  # 이틀 안에 나온 새 곡
    assert all(len(m["embeds"]) <= 10 and m["allowed_mentions"] == {"parse": []} for m in doc["messages"])
    assert not net.calls_to("https://discord.com")  # 디스코드로는 요청하지 않았다
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err + caplog.text + json.dumps(doc)  # 웹훅 URL은 파일에도 로그에도 없다
    assert "send_alerts.py가 보냅니다" in caplog.text


def test_main_never_posts_to_discord_at_all():
    import inspect
    assert "post" not in inspect.signature(app.main).parameters  # 발송 수단 자체를 갖지 않는다


def test_alerts_file_is_outside_site_so_it_is_never_deployed():
    site = (ROOT / "site").resolve()
    assert site not in (config.ALERTS_DIR.resolve(), *config.ALERTS_DIR.resolve().parents)
    assert "out/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_alerts_file_is_not_written_into_the_site_data_dir(data_dir):
    save_run(data_dir, Net(), T1)
    assert pending() is not None and not [p for p in data_dir.iterdir() if "alert" in p.name.lower()]


def test_dry_run_prints_the_alerts_and_leaves_no_file(data_dir, monkeypatch, capsys, caplog):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)
    with caplog.at_level("DEBUG"):
        assert app.main(["--dry-run"], get=Net(), data_dir=data_dir, now=Clock(T1), sleep=lambda s: None) == 0
    out = capsys.readouterr()
    assert "[디스코드 dry-run]" in out.out and "새 커버곡" in out.out
    assert pending() is None  # 파일이 남으면 나중에 send_alerts.py가 dry-run의 알림을 실제로 보낼 수 있다
    assert "SECRET" not in out.out + out.err + caplog.text


def test_no_discord_flag_leaves_no_file_and_prints_nothing(data_dir, capsys):
    assert save_run(data_dir, Net(), T1, "--no-discord") == 0
    assert pending() is None and "디스코드 dry-run" not in capsys.readouterr().out


def test_no_alerts_means_no_file(data_dir):
    save_run(data_dir, Net(), T1)
    assert pending() is not None
    save_run(data_dir, Net(), T2, "--local-state")  # 새로 볼 것이 없다
    assert pending() is None


def test_a_stale_file_is_discarded_even_if_the_run_fails_early(data_dir):
    save_run(data_dir, Net(), T1)
    assert pending() is not None
    assert save_run(data_dir, Net(state_status=500), T2) == 1  # 이전 상태를 못 읽어 중단 (exit 1)
    assert pending() is None  # 옛 알림이 남아 있다가 나가는 일이 없다


def test_a_dry_run_discards_a_stale_file_too(data_dir):
    save_run(data_dir, Net(), T1)
    run(data_dir, Net(), T2, "--local-state")
    assert pending() is None


def test_a_crash_in_the_alert_stage_does_not_fail_the_run(data_dir, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError(f"unexpected {HOOK}")
    monkeypatch.setattr(app.discord, "build_messages", boom)
    with caplog.at_level("INFO"):  # traceback 상세는 DEBUG에서만 — 기본 수준에서는 종류만 보인다
        assert save_run(data_dir, Net(), T1) == 0
    assert "알림 처리 중 오류(RuntimeError)" in caplog.text and "SECRET" not in caplog.text
    assert read(data_dir, "news")["updatedAt"] == T1 and pending() is None


def test_an_unwritable_alerts_file_only_warns(data_dir, tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("파일이라 폴더를 만들 수 없다", encoding="utf-8")
    bad = blocker / "out" / "alerts.json"
    with caplog.at_level("WARNING"):
        assert app.main([], get=Net(), data_dir=data_dir, alerts_file=bad, now=Clock(T1), sleep=lambda s: None) == 0
    assert "알림 처리 중 오류" in caplog.text and read(data_dir, "news")["updatedAt"] == T1


def test_second_run_has_nothing_new_to_leave(data_dir):
    save_run(data_dir, Net(), T1)
    first = pending()
    save_run(data_dir, Net(), T2, "--local-state")
    assert first["messages"] and pending() is None  # 이미 본 항목은 다시 알리지 않는다


def test_a_failed_deploy_cannot_leak_alerts_because_nothing_is_sent_here(data_dir):
    """배포가 실패하면 send_alerts 단계가 돌지 않는다. main은 보내지 않고 파일만 남기므로, 같은 항목이 다음 실행에 다시 새 것이어도 중복 발송은 없다."""
    net = Net()
    save_run(data_dir, net, T1)
    assert not net.calls_to("https://discord.com") and pending() is not None


def test_old_videos_are_not_alerted_on_a_first_run(data_dir, capsys):
    run(data_dir, Net(), T1, "--only", "youtube")  # T1은 최신 영상보다 42시간 뒤
    out = capsys.readouterr().out
    assert any(i["id"].startswith("yt-") for i in read(data_dir, "news")["items"]) and "ytimg" not in out and "dry-run" not in out


def test_only_videos_within_six_hours_are_alerted(data_dir, capsys):
    import re
    from datetime import timedelta
    from updater import timeutil
    published = re.findall(r"<published>([^<]+)</published>", (FIXTURES / "youtube_rss_lize.xml").read_text(encoding="utf-8"))
    clock = timeutil.parse_kst(LIZE_CLOSE_TO_VIDEOS)
    inside = [p for p in published if clock - timeutil.parse_kst(timeutil.to_kst_iso(p)) <= timedelta(hours=6)]
    assert 1 <= len(inside) < len(published)  # 시험 데이터가 경계를 가르는지
    run(data_dir, Net(), LIZE_CLOSE_TO_VIDEOS, "--only", "youtube")
    out = capsys.readouterr().out
    assert f"알림 {len(inside)}건" in out and out.count("썸네일 https://i.ytimg.com/vi/") == len(inside)


# --- 방송 시작: since 규칙 (치지직 → status → 알림 파일) ---
def lize_id(data_dir):
    return people(data_dir)[2]["lize"]


def live_run(data_dir, net, clock, *extra):
    return save_run(data_dir, net, clock, "--only", "chzzk", *extra)


def test_live_start_is_left_once_with_title_link_and_member_color(data_dir):
    live_run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T20:40:00+09:00")  # since 20:30:10 → 10분 전
    (e,) = pending_embeds()
    assert e["author"]["name"] == "아카네 리제 · 방송 시작" and e["title"] == "합성 방송 제목 (테스트용)"
    assert e["url"] == f"https://chzzk.naver.com/live/{lize_id(data_dir)}" and e["color"] == 0xC8352E
    assert e["timestamp"] == "2026-10-06T20:30:10+09:00"


def test_same_broadcast_is_not_left_again_even_after_a_long_gap(data_dir):
    net = Net(live={lize_id(data_dir)})
    live_run(data_dir, net, "2026-10-06T20:40:00+09:00")
    assert len(pending_embeds()) == 1
    live_run(data_dir, net, "2026-10-06T23:30:00+09:00", "--local-state")  # 확인이 3시간 가까이 비었다가 같은 방송(같은 since)
    assert pending() is None


def test_a_new_broadcast_with_a_new_since_is_left_again(data_dir):
    live_run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T20:40:00+09:00")
    live_run(data_dir, Net(live={lize_id(data_dir)}, open_date="2026-10-06 22:10:00"), "2026-10-06T22:20:00+09:00", "--local-state")
    (e,) = pending_embeds()
    assert e["timestamp"] == "2026-10-06T22:10:00+09:00"


def test_a_broadcast_that_started_over_an_hour_ago_is_not_left(data_dir):
    live_run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T21:45:00+09:00")  # since 20:30:10 → 75분 전: 늦은 알림
    assert pending() is None and read(data_dir, "status")["members"]["lize"]["live"]["on"] is True  # 방송 중 표시는 그대로


def test_a_failed_check_never_alerts(data_dir):
    ids = set(people(data_dir)[2].values())
    live_run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T20:40:00+09:00")
    assert len(pending_embeds()) == 1
    live_run(data_dir, Net(live={lize_id(data_dir)}, chzzk_fail=ids), "2026-10-06T20:50:00+09:00", "--local-state")
    assert pending() is None


def test_without_since_the_old_off_to_on_rule_applies(data_dir):
    net = Net(live={lize_id(data_dir)}, open_date=None)  # openDate가 없는 응답 → since 없음
    live_run(data_dir, net, "2026-10-06T20:40:00+09:00")
    assert len(pending_embeds()) == 1 and "since" not in read(data_dir, "status")["members"]["lize"]["live"]
    live_run(data_dir, net, "2026-10-06T23:30:00+09:00", "--local-state")  # 켜짐 → 켜짐
    assert pending() is None
    live_run(data_dir, Net(), "2026-10-06T23:40:00+09:00", "--local-state")  # 꺼짐
    assert pending() is None
    live_run(data_dir, net, "2026-10-06T23:50:00+09:00", "--local-state")  # 꺼짐 → 켜짐
    assert len(pending_embeds()) == 1


def test_live_alerts_do_not_appear_when_chzzk_is_not_run(data_dir):
    save_run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T20:40:00+09:00", "--only", "avatar")
    assert pending() is None


def test_dry_run_lists_the_live_alert_first(data_dir, capsys):
    run(data_dir, Net(live={lize_id(data_dir)}), "2026-10-06T20:40:00+09:00", "--only", "chzzk,news")
    out = capsys.readouterr().out
    assert out.index("아카네 리제 · 방송 시작") < out.index("공지")


# --- 두 단계가 만나는 계약: main이 남긴 파일 → send_alerts가 그대로 발송 ---
def test_main_and_send_alerts_work_together_through_the_file_only(data_dir):
    import send_alerts
    net = Net()
    assert save_run(data_dir, net, T1) == 0
    doc = pending()
    post = PostRecorder()
    assert send_alerts.main([], post=post, sleep=lambda s: None, environ={"DISCORD_WEBHOOK_URL": HOOK}) == 0
    assert [p for _, p in post.calls] == doc["messages"] and all(u == HOOK for u, _ in post.calls)  # 파일 내용이 그대로 나간다
    assert not config.ALERTS_FILE.exists()
    assert not net.calls_to("https://discord.com")  # main 쪽은 처음부터 끝까지 디스코드를 부르지 않았다


class PostRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, payload, **kw):
        self.calls.append((url, payload))
        return make_response(204)



# ============================ 유튜브: API 기본, RSS는 대체 =======================
from fakeapi import KANGJI as KANGJI_YT, KEY, LIZE as LIZE_YT, OFFICIAL as OFFICIAL_YT_ID, FakeApi, http_error, uploads_of  # noqa: E402

RSS_URL = "https://www.youtube.com/feeds"
API_URL = config.YOUTUBE_API_URL
SECRET_FILES = ("news", "catalog", "status", "members")


def api_run(data_dir, net, clock=T1, *extra, key=KEY, dry=True, actions=False):
    """YouTube API 키를 환경변수로 넘겨 실행 (키가 None이면 환경에 없는 것과 같다). actions=True면 GitHub Actions 환경을 흉내 낸다."""
    argv = (["--dry-run"] if dry else []) + list(extra)
    environ = {**({"YOUTUBE_API_KEY": key} if key else {}), **({"GITHUB_ACTIONS": "true"} if actions else {})}
    return app.main(argv, get=net, data_dir=data_dir, now=Clock(clock), sleep=lambda s: None, environ=environ)


def written_text(data_dir):
    """이번 실행이 남긴 모든 파일의 내용 (데이터 + 알림 파일)."""
    texts = [p.read_text(encoding="utf-8") for p in data_dir.glob("*.json")]
    if config.ALERTS_FILE.exists():
        texts.append(config.ALERTS_FILE.read_text(encoding="utf-8"))
    return "\n".join(texts)


def test_with_a_key_videos_come_from_the_api_and_rss_is_not_requested(data_dir):
    fake = FakeApi()
    net = Net(api=fake)
    assert api_run(data_dir, net, T1, "--only", "youtube") == 0
    assert net.calls_to(RSS_URL) == []  # API가 기본이라 RSS는 부르지 않는다
    # 수집: channels.list 1 + playlistItems 12(채널당 1). 이어서 쇼츠 판별: 영상이 있는 3채널 × (UUSH + UULF) = playlistItems 6 (가짜 목록이 비어 있어 전부 미정)
    assert fake.endpoints() == ["channels"] + ["playlistItems"] * 12 + ["playlistItems"] * 6
    videos = [i for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-")]
    assert len(videos) == 15 + 15 + 15 and all(v["date"].endswith("+09:00") and v["added"] == T1 for v in videos)
    assert {v["source"] for v in videos} == {"강지 유튜브", "아카네 리제 유튜브", "스텔라이브 공식 유튜브"}


def test_every_api_call_carries_the_key_in_the_header_only(data_dir):
    fake = FakeApi()
    api_run(data_dir, Net(api=fake), T1, "--only", "youtube")
    assert fake.calls and all(kw["headers"] == {"X-Goog-Api-Key": KEY} and KEY not in url and "key=" not in url for url, kw in fake.calls)


def test_upload_playlist_ids_are_cached_in_status_and_reused_next_run(data_dir):
    people_ = people(data_dir)[1]
    api_run(data_dir, Net(api=FakeApi()), T1, "--only", "youtube")
    st = read(data_dir, "status")["members"]
    assert {k: v["uploads"] for k, v in st.items()} == {**{k: uploads_of(read(data_dir, "members")["members"][k]["yt_id"]) for k in people_}, "official": uploads_of(OFFICIAL_YT_ID)}
    assert read(data_dir, "status")["updatedAt"] == T1
    fake2 = FakeApi()
    api_run(data_dir, Net(api=fake2), T2, "--only", "youtube", "--local-state")
    # 캐시 덕분에 channels.list를 다시 부르지 않는다. playlistItems는 수집 12 + 쇼츠 판별 재시도 6 (30분 전에 처음 본 영상이라 아직 미정)
    assert "channels" not in fake2.endpoints() and fake2.endpoints() == ["playlistItems"] * 18


def test_the_cache_survives_other_sources_rewriting_status(data_dir):
    api_run(data_dir, Net(api=FakeApi()), T1, "--only", "youtube")
    api_run(data_dir, Net(), T2, "--only", "avatar,chzzk", "--local-state")  # 아바타·방송이 status를 다시 써도
    assert all(v.get("uploads") for v in read(data_dir, "status")["members"].values())  # 캐시는 그대로


def test_without_a_key_rss_is_used_and_the_api_is_never_called(data_dir, caplog):
    net = Net()  # api=None: API가 불리면 AssertionError → 소스 실패로 드러난다
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1, "--only", "youtube", key=None) == 0
    assert net.calls_to(API_URL) == [] and net.calls_to(RSS_URL)
    assert "YOUTUBE_API_KEY가 없어 RSS로 수집합니다" in caplog.text
    assert any(i["id"].startswith("yt-") for i in read(data_dir, "news")["items"])
    assert not any(a for a in read(data_dir, "status")["members"].values() if "uploads" in a)  # RSS 경로는 캐시를 만들지 않는다


def test_a_blank_key_counts_as_missing(data_dir):
    net = Net()
    assert api_run(data_dir, net, T1, "--only", "youtube", key="   ") == 0 and net.calls_to(API_URL) == [] and net.calls_to(RSS_URL)


def test_quota_exceeded_on_the_first_call_falls_back_to_rss_for_every_channel(data_dir, caplog):
    fake = FakeApi(fail={("channels", None): http_error(403, "youtube_api_error_quota.json")})
    net = Net(api=fake)
    with caplog.at_level("WARNING"):
        assert api_run(data_dir, net, T1, "--only", "youtube") == 0
    assert "YouTube API 할당량 초과 — 남은 12개 채널은 RSS로 수집합니다" in caplog.text
    assert len(net.calls_to(RSS_URL)) == 12 and fake.endpoints() == ["channels"]
    assert any(i["id"].startswith("yt-") for i in read(data_dir, "news")["items"])


def test_quota_exceeded_midway_uses_rss_only_for_the_channels_left(data_dir, caplog):
    fake = FakeApi(quota_after=3)  # 강지·유니·후야까지 API, 히나부터 할당량 초과
    net = Net(api=fake)
    members_ = read(data_dir, "members")
    left = [members_["members"][k]["yt_id"] for k in list(members_["members"])[3:] if members_["members"][k].get("yt_id")] + [OFFICIAL_YT_ID]
    with caplog.at_level("WARNING"):
        assert api_run(data_dir, net, T1, "--only", "youtube") == 0
    asked = [u.split("channel_id=")[1] for u in net.calls_to(RSS_URL)]
    assert asked == left and len(left) == 9  # 못 한 9개 채널만 RSS
    assert "남은 9개 채널은 RSS" in caplog.text
    ids = [i["id"] for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-")]
    assert len(ids) == len(set(ids)) and any(i["source"] == "강지 유튜브" for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-"))


KEY_REJECTIONS = [
    ("youtube_api_error_badkey.json", 400, "HTTP 400 badRequest"),   # 실제 응답: 엉터리 키
    ("youtube_api_error_nokey.json", 403, "HTTP 403 forbidden"),     # 실제 응답: 키 없음
    ({"error": {"errors": [{"reason": "accessNotConfigured"}]}}, 403, "HTTP 403 accessNotConfigured"),  # API가 꺼져 있음
    ({"error": {"errors": [{"reason": "ipRefererBlocked"}]}}, 403, "HTTP 403 ipRefererBlocked"),        # 키 제한에 걸림
]


@pytest.mark.parametrize("body, status, detail", KEY_REJECTIONS)
def test_a_rejected_key_falls_back_to_rss_and_leaves_a_warning_annotation_on_actions(data_dir, capsys, caplog, body, status, detail):
    fake = FakeApi(fail={("channels", None): http_error(status, body)})
    net = Net(api=fake)
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1, "--only", "youtube", actions=True) == 0  # 대체했으니 실패가 아니다
    assert len(net.calls_to(RSS_URL)) == 12 and fake.endpoints() == ["channels"]  # API는 한 번만 부르고 12개 채널 모두 RSS로
    assert any(i["id"].startswith("yt-") for i in read(data_dir, "news")["items"])
    out = capsys.readouterr().out
    assert f"::warning title=YouTube API::YouTube API 키 확인 필요 ({detail})" in out  # Actions 실행 요약에 보이는 주석
    assert out.count("::warning") == 1  # 주석은 한 번, 한 줄
    assert f"YouTube API 키 확인 필요 ({detail}) — 남은 12개 채널은 RSS로 수집합니다" in caplog.text
    assert KEY not in out + caplog.text


def test_the_key_warning_annotation_is_printed_only_on_actions(data_dir, capsys):
    api_run(data_dir, Net(api=FakeApi(fail={("channels", None): http_error(400, "youtube_api_error_badkey.json")})), T1, "--only", "youtube")
    assert "::warning" not in capsys.readouterr().out  # 로컬에서는 로그 경고만


def test_a_key_rejected_midway_uses_rss_only_for_the_channels_left(data_dir, capsys):
    fake = FakeApi(reject_after=3)  # 강지·유니·후야까지 API, 히나부터 키 거부
    net = Net(api=fake)
    members_ = read(data_dir, "members")
    left = [members_["members"][k]["yt_id"] for k in list(members_["members"])[3:] if members_["members"][k].get("yt_id")] + [OFFICIAL_YT_ID]
    assert api_run(data_dir, net, T1, "--only", "youtube", actions=True) == 0
    assert [u.split("channel_id=")[1] for u in net.calls_to(RSS_URL)] == left and len(left) == 9
    assert "::warning title=YouTube API::YouTube API 키 확인 필요 (HTTP 403 forbidden)" in capsys.readouterr().out
    ids = [i["id"] for i in read(data_dir, "news")["items"] if i["id"].startswith("yt-")]
    assert len(ids) == len(set(ids))


def test_quota_exceeded_falls_back_but_is_not_a_key_warning(data_dir, capsys):
    api_run(data_dir, Net(api=FakeApi(fail={("channels", None): http_error(403, "youtube_api_error_quota.json")})), T1, "--only", "youtube", actions=True)
    assert "::warning" not in capsys.readouterr().out  # 할당량 초과는 사람이 고칠 일이 아니라 로그 경고만


@pytest.mark.parametrize("failure", [http_error(500, b"<html>oops</html>"), http_error(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}), requests.ConnectionError("down")])
def test_other_failures_neither_switch_to_rss_nor_annotate(data_dir, capsys, failure):
    fake = FakeApi(fail={("playlistItems", uploads_of(LIZE_YT)): failure})
    net = Net(api=fake)
    assert api_run(data_dir, net, T1, "--only", "youtube", actions=True) == 0
    assert net.calls_to(RSS_URL) == [] and "::warning" not in capsys.readouterr().out


def test_the_key_annotation_never_contains_the_key(data_dir, capsys, caplog):
    leaky = http_error(400, {"error": {"errors": [{"reason": "badRequest", "message": f"bad key {KEY}"}]}})  # 응답 본문에 키가 들어 있어도
    with caplog.at_level("DEBUG"):
        api_run(data_dir, Net(api=FakeApi(fail={("channels", None): leaky})), T1, "--only", "youtube", actions=True)
    out = capsys.readouterr()
    assert KEY not in out.out + out.err + caplog.text + written_text(data_dir)


def test_with_every_key_rejection_and_no_rss_at_all_the_run_still_fails_cleanly(data_dir):
    """키가 거부됐는데 RSS도 전부 실패하면 (이전과 같이) 소스 실패 — 파일은 건드리지 않는다."""
    net = Net(api=FakeApi(fail={("channels", None): http_error(400, "youtube_api_error_badkey.json")}), fail_channels={
        c for c in [read(data_dir, "members")["official"]["yt_id"], *[m["yt_id"] for m in read(data_dir, "members")["members"].values() if m.get("yt_id")]]})
    before = (data_dir / "news.json").read_bytes()
    assert api_run(data_dir, net, T1, "--only", "youtube", actions=True) == 1
    assert (data_dir / "news.json").read_bytes() == before


def test_one_failing_channel_is_isolated_and_logged_without_rss(data_dir, caplog):
    fake = FakeApi(fail={("playlistItems", uploads_of(LIZE_YT)): http_error(500, b"<html>oops</html>")})
    net = Net(api=fake)
    with caplog.at_level("INFO"):
        assert api_run(data_dir, net, T1, "--only", "youtube") == 0
    assert net.calls_to(RSS_URL) == []
    assert "아카네 리제 유튜브: HTTP 500 -" in caplog.text and "일부 실패 1건" in caplog.text
    assert any(i["source"] == "강지 유튜브" for i in read(data_dir, "news")["items"])


def test_the_key_never_appears_in_logs_output_or_any_written_file(data_dir, capsys, caplog):
    """성공·할당량 초과·키 거부·네트워크 오류·낡은 캐시: 어떤 경우에도 키가 로그·출력·파일에 없다 (예외 메시지에 키가 든 URL을 일부러 넣었다)."""
    scenarios = [
        FakeApi(),
        FakeApi(quota_after=2),
        FakeApi(fail={("channels", None): http_error(400, "youtube_api_error_badkey.json")}),
        FakeApi(fail={("playlistItems", uploads_of(LIZE_YT)): requests.ConnectionError(f"boom https://x/?key={KEY}")}),
        FakeApi(fail={("playlistItems", uploads_of(KANGJI_YT)): RuntimeError(f"internal {KEY}")}),
    ]
    with caplog.at_level("DEBUG"):
        for fake in scenarios:
            api_run(data_dir, Net(api=fake), T1, "--only", "youtube,news")
            api_run(data_dir, Net(api=fake), T2, "--only", "youtube", "--local-state", dry=False)
    out = capsys.readouterr()
    assert KEY not in caplog.text + out.out + out.err and KEY not in written_text(data_dir)
    assert "TESTKEY" not in written_text(data_dir)


def test_a_secret_hidden_in_an_exception_is_masked_in_the_source_failure_log(data_dir, caplog):
    """우리 코드가 키를 메시지에 넣지 않더라도, 예상 밖 경로(예: RuntimeError 메시지)로 새면 main이 가린다."""
    def leaky(url, **kw):
        raise RuntimeError(f"unexpected {KEY}")
    net = Net(api=leaky)
    with caplog.at_level("DEBUG"):
        api_run(data_dir, net, T1, "--only", "youtube,news")
    assert KEY not in caplog.text


def test_with_a_key_the_previous_status_must_be_readable_but_not_without(data_dir):
    state_500 = {"news": 404, "catalog": 404, "status": 500}
    assert api_run(data_dir, Net(api=FakeApi(), state_status=state_500), T1, "--only", "youtube") == 1  # 캐시를 읽지 못하면 중단
    assert api_run(data_dir, Net(state_status=state_500), T1, "--only", "youtube", key=None) == 0  # RSS 경로는 status가 필요 없다


def test_api_videos_flow_into_alerts_like_rss_videos(data_dir, capsys):
    from datetime import timedelta
    from updater import timeutil
    raw = json.loads((FIXTURES / "youtube_api_playlist_lize.json").read_text(encoding="utf-8"))["items"]
    newest = max(timeutil.parse_kst(timeutil.to_kst_iso(i["contentDetails"]["videoPublishedAt"])) for i in raw)
    clock = timeutil.to_kst_iso(newest + timedelta(minutes=30))  # 가장 최근 영상이 30분 전
    empty = {"items": []}
    api_run(data_dir, Net(api=FakeApi(playlists={uploads_of(KANGJI_YT): empty, uploads_of(OFFICIAL_YT_ID): empty})), clock, "--only", "youtube")
    out = capsys.readouterr().out
    assert "[디스코드 dry-run]" in out and "아카네 리제 · 영상" in out and "썸네일 https://i.ytimg.com/vi/" in out
