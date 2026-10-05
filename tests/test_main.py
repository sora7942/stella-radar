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
    return d


def default_songs():
    return [
        song(2001, "COVER", artist="Akane Lize", date="2026-10-05", title="새 커버곡"),  # 최근 → news에도 오른다
        song(2002, "EP", artist="Yuzuha Riko", date="2026-07-24", leaf="EP", title="옛 EP"),
        song(2003, "COVER", artist="Aokumo Rin", date="2024-01-01", title="오래된 커버"),
    ]


class Net:
    """가짜 네트워크: 배포본(404), 유튜브 RSS·공지(픽스처), 음악 사이트(Site)."""

    def __init__(self, *, fail_channels=(), state_status=404, songs=None, down=False, news_fails=False):
        self.calls = []
        self.fail_channels, self.state_status, self.down, self.news_fails = set(fail_channels), state_status, down, news_fails
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
    assert any("/data/news.json?t=" in u for u in net.calls) and any("/data/catalog.json?t=" in u for u in net.calls)
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
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog")}
    assert run(data_dir, Net(down=True)) == 1
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog")} == before


@pytest.mark.parametrize("status", [500, 503, 403])
def test_unreadable_previous_state_exits_1_and_writes_nothing(data_dir, status):
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog")}
    assert run(data_dir, Net(state_status=status)) == 1  # 시드로 되돌아가서 덮어쓰지 않는다
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in ("news", "catalog")} == before


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
    real_before = {n: (config.DATA_DIR / f"{n}.json").read_bytes() for n in ("news", "catalog")}
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/SECRET-ID/SECRET-TOKEN")
    with caplog.at_level("DEBUG"):
        run(data_dir, Net())
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err + caplog.text
    assert {n: (config.DATA_DIR / f"{n}.json").read_bytes() for n in ("news", "catalog")} == real_before  # 테스트는 tmp에만 쓴다
