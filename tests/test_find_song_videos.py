"""tools/find_song_videos.py — 네트워크·실제 API 없음. 응답은 search.list 문서 형식을 따른 최소 가짜(실호출 응답은 저장소에 두지 않는다).
핵심 불변 조건: ① songs.json을 쓰지 않는다 ② 키는 헤더로만 가고 어디에도 남지 않는다 ③ 호출 수 상한을 지킨다 ④ 업데이터는 tools/를 import하지 않는다."""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from conftest import ROOT, make_response
from fakeapi import KEY, http_error
from updater import config

TOOL = ROOT / "tools" / "find_song_videos.py"
SONGS = ROOT / "site" / "data" / "songs.json"

spec = importlib.util.spec_from_file_location("find_song_videos", TOOL)
fsv = importlib.util.module_from_spec(spec)
sys.modules["find_song_videos"] = fsv  # dataclass가 모듈을 찾을 수 있게 exec 전에 등록
spec.loader.exec_module(fsv)


@pytest.fixture
def docs():
    return json.loads(SONGS.read_text(encoding="utf-8")), json.loads((ROOT / "site" / "data" / "members.json").read_text(encoding="utf-8"))


def item(video_id, title="영상", channel="채널", published="2026-01-02T00:00:00Z"):
    return {"id": {"kind": "youtube#video", "videoId": video_id}, "snippet": {"title": title, "channelTitle": channel, "publishedAt": published}}


def ok(*items):
    return make_response(200, json.dumps({"kind": "youtube#searchListResponse", "items": list(items)}))


class FakeSearch:
    """http.get 대용. replies: (channelId 또는 None) → 응답 또는 예외의 목록(호출 순서대로). 없으면 빈 결과."""

    def __init__(self, replies=None, default=None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.default = default if default is not None else ok()
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert urlparse(url).path.endswith("/search")
        queue = self.replies.get(q.get("channelId"))
        out = queue.pop(0) if queue else self.default
        if isinstance(out, Exception):
            raise out
        return out

    def query(self, n):
        return {k: v[0] for k, v in parse_qs(urlparse(self.calls[n][0]).query).items()}


# ================================ 계획 ========================================
def test_plan_covers_exactly_the_ten_songs_with_eleven_first_pass_calls(docs):
    songs, members = docs
    targets, warnings = fsv.find_targets(songs, members, fsv.TARGET_TITLES)
    assert warnings == []
    assert [t.title for t in targets] == list(fsv.TARGET_TITLES)
    queries = fsv.first_pass(targets)
    assert len(queries) == 11  # 불꽃(2명)만 채널이 둘
    assert len(queries) * fsv.SEARCH_UNITS == 1100
    assert (len(queries) + len(targets)) * fsv.SEARCH_UNITS == 2100  # 최악: 모든 곡이 2차까지


def test_two_member_song_searches_both_channels_and_tak_collab_only_shibuki(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, fsv.TARGET_TITLES)
    by = {t.title: [q for q in fsv.first_pass([t])] for t in targets}
    assert {q.channel_id for q in by["불꽃"]} == {members["members"]["rin"]["yt_id"], members["members"]["nana"]["yt_id"]}
    assert [q.channel_id for q in by["도깨비꽃"]] == [members["members"]["shibuki"]["yt_id"]]


def test_song_with_yt_or_missing_or_duplicated_is_skipped_with_a_warning(docs):
    songs, members = docs
    songs["items"][0]["yt"] = "abcdefghijk"  # SYNC 100%
    songs["items"].append(dict(songs["items"][1], title="불꽃"))  # 제목이 겹침
    targets, warnings = fsv.find_targets(songs, members, ("SYNC 100%", "불꽃", "없는 곡", "눈꽃"))
    assert [t.title for t in targets] == ["눈꽃"]
    assert len(warnings) == 3 and any("이미 yt" in w for w in warnings) and any("없음" in w for w in warnings)


def test_plan_text_shows_cost_without_a_key_or_network(docs, capsys):
    assert fsv.main(["--plan"], get=None, environ={}) == 0  # 키 없음·get 없음 — 네트워크를 건드리면 실패한다
    out = capsys.readouterr().out
    assert "1차 호출 11회 = 1,100유닛" in out and "2,100유닛" in out


# ================================ 호출 ========================================
def test_key_goes_in_the_header_only_and_params_are_as_planned(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃",))
    fake = FakeSearch({members["members"]["kangji"]["yt_id"]: [ok(item("vid00000001"))]})
    fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    url, kw = fake.calls[0]
    assert KEY not in url and kw["headers"] == {config.YOUTUBE_API_KEY_HEADER: KEY}
    assert fake.query(0) == {"part": "snippet", "type": "video", "maxResults": "3", "q": "눈꽃", "channelId": members["members"]["kangji"]["yt_id"]}


def test_global_search_only_when_channel_search_found_nothing(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃", "여로"))  # 여로는 대상 10곡이 아니지만 run은 제목 검사를 하지 않는다
    fake = FakeSearch({members["members"]["kangji"]["yt_id"]: [ok(item("vid00000001"))]})  # 눈꽃은 있음, 여로(타비)는 없음
    results, calls, stopped = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    assert stopped is None and calls == 3  # 채널 2 + 여로의 전체 검색 1
    last = fake.query(2)
    assert "channelId" not in last and last["q"] == f"{members['members']['tabi']['n']} 여로"
    assert [c.video_id for _, cs in results[0].found for c in cs] == ["vid00000001"]


def test_titles_are_html_unescaped_and_dates_are_kst(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃",))
    fake = FakeSearch(default=ok(item("vid00000001", title="눈꽃 &amp; Co &#39;MV&#39;", channel="강지 &amp; 친구", published="2026-01-02T20:00:00Z")))
    results, _, _ = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    c = results[0].found[0][1][0]
    assert (c.title, c.channel, c.published) == ("눈꽃 & Co 'MV'", "강지 & 친구", "2026-01-03")  # 20:00Z = 다음 날 05:00 KST
    assert c.url == "https://www.youtube.com/watch?v=vid00000001"


def test_same_video_from_two_channels_is_listed_once(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("불꽃",))
    fake = FakeSearch(default=ok(item("same0000001"), item("only0000001")))
    results, calls, _ = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    text = fsv.results_text(results, calls, None)
    assert text.count("same0000001") == 2  # 영상 ID 줄 + URL 줄 = 한 번만 나열
    assert "API 호출 2회 = 200유닛" in text


def test_call_cap_is_never_exceeded(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, fsv.TARGET_TITLES)
    fake = FakeSearch()  # 전부 빈 결과 → 2차까지 간다
    _, calls, stopped = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None, max_calls=15)
    assert calls == len(fake.calls) == 15 and "상한" in stopped
    _, calls, stopped = fsv.run(targets, members, KEY, get=(full := FakeSearch()), sleep=lambda s: None)
    assert calls == len(full.calls) == 21 and stopped is None  # 기본 상한 = 최악의 경우


def test_requests_are_spaced_by_the_request_delay(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃", "꿈의 신호"))
    waits = []
    fsv.run(targets, members, KEY, get=FakeSearch(default=ok(item("vid00000001"))), sleep=waits.append)
    assert waits == [config.REQUEST_DELAY]  # 호출 2회 사이 1번


def test_main_refuses_when_first_pass_exceeds_the_cap(capsys):
    assert fsv.main(["--max-calls", "5"], get=None, environ={}) == 2


def test_main_without_a_key_stops_before_any_request(capsys):
    assert fsv.main([], get=None, environ={}) == 2  # get=None — 호출하면 TypeError
    assert config.YOUTUBE_API_KEY_ENV in capsys.readouterr().err


def test_only_rejects_titles_outside_the_ten(capsys):
    assert fsv.main(["--only", "여로"], get=None, environ={}) == 2


# ============================ 오류: 중단과 키 비노출 ============================
@pytest.mark.parametrize("fail_body, expect", [
    ("youtube_api_error_quota.json", "할당량"),
    ("youtube_api_error_nokey.json", "키 거부"),
])
def test_quota_or_key_rejection_stops_and_reports_without_the_key(docs, caplog, capsys, fail_body, expect):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃", "여로"))
    fake = FakeSearch(default=http_error(403, fail_body))
    results, calls, stopped = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    assert calls == 1 and expect in stopped  # 첫 호출에서 멈춘다
    text = fsv.results_text(results, calls, stopped)
    assert KEY not in text and KEY not in stopped and KEY not in caplog.text


def test_other_failures_are_recorded_per_song_and_do_not_stop_the_run(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃", "꿈의 신호"))
    boom = http_error(500, {"error": {"errors": [{"reason": "backendError"}]}})
    fake = FakeSearch({members["members"]["kangji"]["yt_id"]: [boom]}, default=ok(item("vid00000001")))
    results, calls, stopped = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    assert stopped is None and calls == 2
    assert results[0].errors == [f"{members['members']['kangji']['n']}: HTTP 500 backendError"]
    assert results[1].found and not results[1].errors
    assert len(fake.calls) == 2  # 오류가 난 곡은 전체 검색으로 돌리지 않는다 (비용)


def test_network_errors_are_recorded_by_type_only(docs):
    songs, members = docs
    targets, _ = fsv.find_targets(songs, members, ("눈꽃",))
    fake = FakeSearch(default=requests.ConnectionError(f"failed https://x/?key={KEY}"))
    results, _, _ = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    assert results[0].errors[0].endswith("ConnectionError") and KEY not in str(results[0].errors)


# ============================ songs.json은 쓰지 않는다 ==========================
def test_run_leaves_the_data_files_untouched(capsys):
    """내용(해시)뿐 아니라 수정 시각도 본다 — 같은 내용을 다시 저장하는 코드는 해시만으로는 못 잡는다(Windows CRLF 파일은 읽고 다시 쓰면 바이트가 같다)."""
    files = [SONGS, ROOT / "site" / "data" / "members.json"]
    snap = lambda: [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files]  # noqa: E731
    before = snap()
    fake = FakeSearch(default=ok(item("vid00000001")))
    assert fsv.main(["--only", "눈꽃"], get=fake, sleep=lambda s: None, environ={config.YOUTUBE_API_KEY_ENV: KEY}) == 0
    assert snap() == before
    assert KEY not in capsys.readouterr().out


def test_tool_source_has_no_file_writing_calls():
    text = TOOL.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for pattern in (r"write_text", r"write_bytes", r"json\.dump\(", r"\bopen\(", r"\.write\(", r"shutil", r"os\.(rename|replace|remove)"):
        assert not re.search(pattern, code), f"도구가 파일을 쓸 수 있다: {pattern}"


# ============================ 경계: 업데이터는 tools/를 모른다 ===================
def test_no_updater_code_imports_tools():
    offenders = []
    for path in [ROOT / "main.py", ROOT / "send_alerts.py", *(ROOT / "updater").rglob("*.py")]:
        if re.search(r"^\s*(from|import)\s+tools\b", path.read_text(encoding="utf-8"), re.MULTILINE):
            offenders.append(path.name)
    assert offenders == []


# ============================ 공식 채널 표시 ====================================
def test_candidates_are_marked_by_channel_kind(docs):
    songs, members = docs
    kangji, official = members["members"]["kangji"]["yt_id"], members["official"]["yt_id"]
    lize = members["members"]["lize"]["yt_id"]
    targets, _ = fsv.find_targets(songs, members, ("눈꽃",))
    snip = lambda vid, cid: {**item(vid), "snippet": {**item(vid)["snippet"], "channelId": cid}}  # noqa: E731
    fake = FakeSearch(default=ok(snip("vid00000001", kangji), snip("vid00000002", official), snip("vid00000003", lize), snip("vid00000004", "UCexternal000000000000000")))
    results, calls, _ = fsv.run(targets, members, KEY, get=fake, sleep=lambda s: None)
    text = fsv.results_text(results, calls, None, members, {"눈꽃": ["kangji"]})
    assert "✔ 멤버 본인 채널(강지)" in text and "✔ 스텔라이브 공식 채널" in text
    assert "△ 다른 멤버 채널(" in text and "✘ 외부 채널(공식 아님)" in text


def test_channel_kind_without_members_doc_does_not_guess():
    assert fsv.channel_kind("UCx", None, []) == "채널 구분 불가" and fsv.channel_kind("", {"members": {}}, []) == "채널 구분 불가"
