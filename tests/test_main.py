"""main.py 전체 흐름을 네트워크 없이: get·data_dir·시계를 주입한다."""
import json
import shutil

import pytest
import requests

from conftest import FIXTURES, ROOT, make_response
from updater import config
import main as app

T1 = "2026-10-06T10:00:00+09:00"
T2 = "2026-10-06T10:30:00+09:00"


class Clock:
    def __init__(self, iso):
        from datetime import datetime

        self.value = datetime.fromisoformat(iso)

    def __call__(self):
        return self.value


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(ROOT / "site" / "data", d)
    return d


class Net:
    """배포본은 404(최초 배포 전), 유튜브 RSS는 픽스처로 응답하는 가짜 네트워크."""

    def __init__(self, fail_channels=(), state_status=404):
        self.calls = []
        self.fail_channels = set(fail_channels)
        self.state_status = state_status

    def __call__(self, url, **kw):
        self.calls.append(url)
        if "/data/" in url:  # 이전 상태(배포본)
            resp = make_response(self.state_status, "")
        elif "feeds/videos.xml" in url:
            cid = url.split("channel_id=")[1]
            if cid in self.fail_channels or "*" in self.fail_channels:
                raise requests.ConnectionError("down")
            name = "youtube_rss_official.xml" if cid == "UC2b4WRE5BZ6SIUWBeJU8rwg" else "youtube_rss_lize.xml"
            resp = make_response(200, (FIXTURES / name).read_bytes())
        else:
            raise AssertionError(f"예상 밖의 URL: {url}")
        if resp.status_code >= 400:
            raise requests.HTTPError(str(resp.status_code), response=resp)
        return resp


def run(data_dir, net, clock=T1, *extra):
    return app.main(["--dry-run", *extra], get=net, data_dir=data_dir, now=Clock(clock), sleep=lambda s: None)


def news(data_dir):
    return json.loads((data_dir / "news.json").read_text(encoding="utf-8"))


def test_first_run_adds_videos_and_keeps_seeds(data_dir):
    seeds = news(data_dir)["items"]
    assert run(data_dir, Net()) == 0
    doc = news(data_dir)
    assert doc["updatedAt"] == T1
    ids = {it["id"] for it in doc["items"]}
    assert {s["id"] for s in seeds} <= ids  # 시드 18개 유지
    by_id = {it["id"]: it for it in doc["items"]}
    for s in seeds:
        assert by_id[s["id"]] == s  # 시드는 한 글자도 안 바뀐다 (added 포함)
    videos = [it for it in doc["items"] if it["id"].startswith("yt-")]
    assert videos and all(v["yt"] and v["date"].endswith("+09:00") and v["added"] == T1 for v in videos)


def test_second_run_only_moves_updated_at(data_dir):
    run(data_dir, Net(), T1)
    first = news(data_dir)
    run(data_dir, Net(), T2, "--local-state")
    second = news(data_dir)
    assert second["updatedAt"] == T2  # 새 항목이 없어도 '마지막 관측'은 갱신
    assert second["items"] == first["items"]  # added 포함 불변


def test_uses_local_state_only_when_deployed_copy_is_404(data_dir):
    net = Net()
    run(data_dir, net)
    assert any("/data/news.json?t=" in u for u in net.calls)  # 배포본을 먼저 시도했다
    net2 = Net()
    run(data_dir, net2, T2, "--local-state")
    assert not any("/data/" in u for u in net2.calls)  # --local-state는 원격을 건드리지 않는다


def test_one_failed_channel_does_not_stop_the_run(data_dir):
    assert run(data_dir, Net(fail_channels={"UC7-m6jQLinZQWIbwm9W-1iw"})) == 0
    assert any(it["id"].startswith("yt-") for it in news(data_dir)["items"])


def test_all_sources_failing_exits_1_and_writes_nothing(data_dir):
    before = (data_dir / "news.json").read_bytes()
    assert run(data_dir, Net(fail_channels={"*"})) == 1
    assert (data_dir / "news.json").read_bytes() == before


@pytest.mark.parametrize("status", [500, 503, 403])
def test_unreadable_previous_state_exits_1_and_writes_nothing(data_dir, status):
    before = (data_dir / "news.json").read_bytes()
    assert run(data_dir, Net(state_status=status)) == 1  # 시드로 되돌아가서 덮어쓰지 않는다
    assert (data_dir / "news.json").read_bytes() == before


def test_unknown_source_is_an_argument_error(data_dir, capsys):
    with pytest.raises(SystemExit) as ei:
        app.main(["--only", "nope"], get=Net(), data_dir=data_dir)
    assert ei.value.code == 2
    assert "nope" in capsys.readouterr().err


def test_only_youtube_is_accepted(data_dir):
    assert run(data_dir, Net(), T1, "--only", "youtube") == 0


def test_output_contains_no_webhook_text(data_dir, capsys, monkeypatch, caplog):
    real_before = (config.DATA_DIR / "news.json").read_bytes()
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/SECRET-ID/SECRET-TOKEN")
    with caplog.at_level("DEBUG"):
        run(data_dir, Net())
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err + caplog.text
    assert (config.DATA_DIR / "news.json").read_bytes() == real_before  # 테스트가 실제 저장소 데이터를 건드리지 않는다
