import copy
import json

import pytest
import requests

from conftest import FakeGet, make_response
from updater import config, state

NOW = "2026-10-06T10:00:00+09:00"


def item(id_, date, **kw):
    base = {"id": id_, "date": date, "cat": "영상", "who": ["lize"], "title": f"title {id_}", "url": f"https://x/{id_}", "source": "src"}
    base.update(kw)
    return base


# ============================ merge_news =====================================
def test_new_item_gets_added_now_and_is_reported_fresh():
    merged, fresh = state.merge_news([], [item("yt-a", "2026-10-06T09:00:00+09:00")], now_iso=NOW)
    assert merged[0]["added"] == NOW
    assert [f["id"] for f in fresh] == ["yt-a"]


def test_inputs_are_not_mutated():
    new = [item("yt-a", "2026-10-06T09:00:00+09:00")]
    snapshot = copy.deepcopy(new)
    state.merge_news([], new, now_iso=NOW)
    assert new == snapshot


def test_duplicate_id_existing_wins_and_added_is_kept():
    old = item("yt-a", "2026-10-01T09:00:00+09:00", added="2026-10-01T09:30:00+09:00", title="원래 제목", who=["lize"])
    newer = item("yt-a", "2026-10-01T09:00:00+09:00", title="바뀐 제목", who=["rin"])
    merged, fresh = state.merge_news([old], [newer], now_iso=NOW)
    assert len(merged) == 1
    assert merged[0]["added"] == "2026-10-01T09:30:00+09:00"  # 절대 안 바뀐다
    assert merged[0]["title"] == "원래 제목"
    assert merged[0]["who"] == ["lize"]
    assert fresh == []


def test_duplicate_within_new_items_first_wins():
    a1 = item("yt-a", "2026-10-06T09:00:00+09:00", title="first")
    a2 = item("yt-a", "2026-10-06T09:00:00+09:00", title="second")
    merged, fresh = state.merge_news([], [a1, a2], now_iso=NOW)
    assert [m["title"] for m in merged] == ["first"]
    assert len(fresh) == 1


def test_sorted_by_date_desc_with_mixed_date_formats():
    items = [
        item("a", "2026-10-03T23:59:59+09:00"),
        item("b", "2026-10-04"),  # 날짜만 = 그날 00:00 KST
        item("c", "2026-10-04T09:00:00+09:00"),
        item("d", "2026-10-05"),
    ]
    merged, _ = state.merge_news([], items, now_iso=NOW)
    assert [m["id"] for m in merged] == ["d", "c", "b", "a"]


def test_sort_compares_instants_not_strings():
    # 문자열 비교로는 +00:00 이 앞서지만 실제로는 +09:00 쪽이 더 이르다
    items = [item("kst", "2026-10-04T08:00:00+09:00"), item("utc", "2026-10-04T00:00:00+00:00")]
    merged, _ = state.merge_news([], items, now_iso=NOW)
    assert [m["id"] for m in merged] == ["utc", "kst"]


def test_trimmed_to_limit_keeping_newest():
    prev = [item(f"old-{i}", f"2026-01-{(i % 28) + 1:02d}T00:00:00+09:00", added="2026-01-01") for i in range(250)]
    new = [item(f"new-{i}", f"2026-10-{(i % 28) + 1:02d}T12:00:00+09:00") for i in range(100)]
    merged, fresh = state.merge_news(prev, new, now_iso=NOW)
    assert len(merged) == config.NEWS_MAX_ITEMS == 300
    assert all(m["id"].startswith("new-") for m in merged[:100])  # 새 항목이 모두 살아남는다
    assert len(fresh) == 100


def test_fresh_includes_items_trimmed_away():
    prev = [item(f"p{i}", "2026-10-05T00:00:00+09:00", added="x") for i in range(3)]
    merged, fresh = state.merge_news(prev, [item("ancient", "2020-01-01")], now_iso=NOW, limit=3)
    assert "ancient" not in [m["id"] for m in merged]
    assert [f["id"] for f in fresh] == ["ancient"]  # 잘렸어도 '이번에 처음 본 항목'


def test_merge_is_idempotent():
    new = [item("yt-a", "2026-10-06T09:00:00+09:00"), item("yt-b", "2026-10-05")]
    first, _ = state.merge_news([], new, now_iso=NOW)
    second, fresh = state.merge_news(first, new, now_iso="2026-10-06T10:30:00+09:00")
    assert second == first
    assert fresh == []


def test_repo_seed_news_survives_merge_untouched():
    seed = json.loads((config.DATA_DIR / "news.json").read_text(encoding="utf-8"))["items"]
    merged, fresh = state.merge_news(seed, [], now_iso=NOW)
    assert {m["id"] for m in merged} == {s["id"] for s in seed}
    assert fresh == []
    by_id = {m["id"]: m for m in merged}
    for s in seed:
        assert by_id[s["id"]] == s  # added 포함 한 글자도 안 바뀐다


# ============================ merge_catalog ===================================
def cat(id_, date, **kw):
    base = {"id": str(id_), "title": f"곡 {id_}", "artist": "Akane Lize", "who": ["lize"], "category": "COVER",
            "kind": "커버", "date": date, "yt": "x", "url": f"https://stellive.me/music/{id_}"}
    base.update(kw)
    return base


def test_catalog_new_items_are_added_and_reported_fresh():
    merged, fresh = state.merge_catalog([cat(1, "2026-01-01")], [cat(2, "2026-02-01")])
    assert [c["id"] for c in merged] == ["2", "1"]
    assert [c["id"] for c in fresh] == ["2"]


def test_catalog_existing_wins_over_new_with_same_id():
    old = cat(1, "2026-01-01", title="원래 제목")
    merged, fresh = state.merge_catalog([old], [cat(1, "2026-01-01", title="바뀐 제목")])
    assert merged == [old] and fresh == []


def test_catalog_sorted_by_date_then_id_desc_with_numeric_ids():
    items = [cat(9, "2026-05-01"), cat(10, "2026-05-01"), cat(2, "2026-06-01"), cat(100, "2025-01-01")]
    merged, _ = state.merge_catalog([], items)
    assert [c["id"] for c in merged] == ["2", "10", "9", "100"]  # 같은 날짜는 번호 큰 것(숫자 비교, '9' > '10' 아님)이 먼저


def test_catalog_is_idempotent_and_does_not_mutate_inputs():
    new = [cat(1, "2026-01-01"), cat(2, "2026-02-01")]
    snapshot = copy.deepcopy(new)
    first, _ = state.merge_catalog([], new)
    second, fresh = state.merge_catalog(first, new)
    assert second == first and fresh == [] and new == snapshot


def test_catalog_has_no_size_cap():
    items = [cat(i, "2026-01-01") for i in range(1, 401)]
    merged, _ = state.merge_catalog([], items)
    assert len(merged) == 400  # news와 달리 카탈로그는 자르지 않는다


# ============================ load_previous ===================================
BASE = "https://site.test/stella-radar/"


def load(name, get, tmp_path, **kw):
    sleeps = kw.pop("sleeps", [])
    return state.load_previous(
        name, site_url=BASE, local_dir=tmp_path, get=get, sleep=sleeps.append, now=lambda: 1234.0, **kw
    )


def write_local(tmp_path, name, doc):
    (tmp_path / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


REMOTE_NEWS = {"updatedAt": "2026-10-06T09:30:00+09:00", "items": [item("yt-remote", "2026-10-06")]}
LOCAL_NEWS = {"updatedAt": None, "items": [item("sl-seed", "2026-10-01")]}


def test_remote_success_is_used_and_url_is_cache_busted(tmp_path):
    write_local(tmp_path, "news", LOCAL_NEWS)
    get = FakeGet(make_response(200, json.dumps(REMOTE_NEWS)))
    doc = load("news", get, tmp_path)
    assert doc["items"][0]["id"] == "yt-remote"
    assert get.calls == [f"{BASE}data/news.json?t=1234"]


def test_404_falls_back_to_local_without_retry(tmp_path):
    write_local(tmp_path, "news", LOCAL_NEWS)
    get = FakeGet(make_response(404, "not found"))
    doc = load("news", get, tmp_path)
    assert doc["items"][0]["id"] == "sl-seed"
    assert len(get.calls) == 1


def test_404_and_no_local_file_gives_empty_default(tmp_path):
    for name, key in (("news", "items"), ("catalog", "items"), ("status", "members")):
        doc = load(name, FakeGet(make_response(404)), tmp_path)
        assert doc["updatedAt"] is None and not doc[key]


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retried_then_fails_instead_of_falling_back(tmp_path, status):
    write_local(tmp_path, "news", LOCAL_NEWS)  # 로컬 시드가 있어도 되돌아가면 안 된다
    get, sleeps = FakeGet(make_response(status)), []
    with pytest.raises(state.StateLoadError):
        load("news", get, tmp_path, sleeps=sleeps)
    assert len(get.calls) == config.STATE_LOAD_ATTEMPTS == 3
    assert sleeps == [1.0, 2.0]  # 지수 백오프


@pytest.mark.parametrize("exc", [requests.ConnectionError("boom"), requests.Timeout("slow")])
def test_network_errors_are_retried_then_fail(tmp_path, exc):
    get = FakeGet(exc)
    with pytest.raises(state.StateLoadError):
        load("news", get, tmp_path)
    assert len(get.calls) == 3


def test_recovers_if_a_retry_succeeds(tmp_path):
    get = FakeGet(make_response(503), make_response(200, json.dumps(REMOTE_NEWS)))
    doc = load("news", get, tmp_path)
    assert doc["items"][0]["id"] == "yt-remote"
    assert len(get.calls) == 2


def test_non_404_client_error_fails_immediately(tmp_path):
    get = FakeGet(make_response(403))
    with pytest.raises(state.StateLoadError):
        load("news", get, tmp_path)
    assert len(get.calls) == 1


@pytest.mark.parametrize("body", ["<html>Pages 점검 중</html>", "{ not json", "[1, 2, 3]", '{"items": "nope"}'])
def test_bad_body_is_a_failure_not_a_fallback(tmp_path, body):
    get = FakeGet(make_response(200, body))
    with pytest.raises(state.StateLoadError):
        load("news", get, tmp_path)
    assert len(get.calls) == 3


def test_status_shape_is_validated(tmp_path):
    get = FakeGet(make_response(200, json.dumps({"updatedAt": None, "items": []})))  # members 없음
    with pytest.raises(state.StateLoadError):
        load("status", get, tmp_path)


def test_local_only_never_touches_network(tmp_path):
    write_local(tmp_path, "news", LOCAL_NEWS)

    def boom(*a, **k):
        raise AssertionError("원격 호출 금지")

    doc = state.load_previous("news", site_url=BASE, local_dir=tmp_path, get=boom, local_only=True)
    assert doc["items"][0]["id"] == "sl-seed"


def test_site_url_without_trailing_slash(tmp_path):
    get = FakeGet(make_response(200, json.dumps(REMOTE_NEWS)))
    state.load_previous("news", site_url="https://site.test/stella-radar", local_dir=tmp_path, get=get, now=lambda: 1.0)
    assert get.calls == ["https://site.test/stella-radar/data/news.json?t=1"]


# ============================ write_json ======================================
def test_write_json_utf8_no_ascii_escape_and_atomic(tmp_path):
    path = tmp_path / "news.json"
    state.write_json(path, {"updatedAt": NOW, "items": [{"title": "아카네 리제 ✦"}]})
    text = path.read_text(encoding="utf-8")
    assert "아카네 리제 ✦" in text and "\\u" not in text
    assert text.endswith("\n")
    assert json.loads(text)["items"][0]["title"] == "아카네 리제 ✦"
    assert [p.name for p in tmp_path.iterdir()] == ["news.json"]  # 임시 파일이 남지 않는다


def test_write_json_failure_leaves_original_intact(tmp_path):
    path = tmp_path / "news.json"
    state.write_json(path, {"ok": True})
    with pytest.raises(TypeError):
        state.write_json(path, {"bad": object()})  # 직렬화 실패
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert [p.name for p in tmp_path.iterdir()] == ["news.json"]


# ============================ auto_events (기능 3) ===============================
AUTO_DOC = {"updatedAt": "2026-10-09T13:00:00+09:00", "processed": {"sl-1": {"at": "2026-10-09T13:00:00+09:00", "result": "none", "tries": 1}}, "items": []}


def test_auto_events_default_has_processed_and_items(tmp_path):
    doc = load("auto_events", FakeGet(make_response(404)), tmp_path)
    assert doc == {"updatedAt": None, "processed": {}, "items": []}


def test_auto_events_remote_is_used_and_404_falls_back_to_the_repo_seed(tmp_path):
    get = FakeGet(make_response(200, json.dumps(AUTO_DOC)))
    assert load("auto_events", get, tmp_path) == AUTO_DOC and "data/auto_events.json?t=" in get.calls[0]
    write_local(tmp_path, "auto_events", AUTO_DOC)
    assert load("auto_events", FakeGet(make_response(404)), tmp_path) == AUTO_DOC


@pytest.mark.parametrize("body", [{"items": []}, {"processed": {}}, {"processed": [], "items": []}, {"processed": {}, "items": {}}, []])
def test_auto_events_shape_is_validated_and_a_bad_body_is_a_failure_not_a_fallback(tmp_path, body):
    write_local(tmp_path, "auto_events", AUTO_DOC)
    with pytest.raises(state.StateLoadError):
        load("auto_events", FakeGet(make_response(200, json.dumps(body))), tmp_path)


def test_the_repo_seed_for_auto_events_is_empty_and_valid():
    seed = json.loads((config.DATA_DIR / "auto_events.json").read_text(encoding="utf-8"))
    assert seed == {"updatedAt": None, "processed": {}, "items": []}
    assert "auto_events" in config.STATE_FILES


# ============================ status 병합 ========================================
def test_status_patch_updates_only_the_patched_fields_and_members():
    prev = {
        "lize": {"avatar": "A", "avatarCheckedAt": "T0", "live": {"on": True, "title": "t"}},
        "tabi": {"avatar": "B", "avatarCheckedAt": "T0", "live": {"on": False}},
    }
    merged = state.merge_status(prev, {"lize": {"live": {"on": False}}})
    assert merged["lize"] == {"avatar": "A", "avatarCheckedAt": "T0", "live": {"on": False}}
    assert merged["tabi"] == prev["tabi"]


def test_status_member_without_patch_keeps_previous_live_on():
    """치지직 요청이 실패한 멤버는 패치가 없다 → 방송 중이던 값이 꺼짐으로 뒤집히지 않는다."""
    prev = {"lize": {"live": {"on": True, "title": "t", "url": "u", "since": "S"}}}
    assert state.merge_status(prev, {"tabi": {"live": {"on": False}}})["lize"] == prev["lize"]


def test_status_new_member_is_added_and_fields_are_in_fixed_order():
    merged = state.merge_status({}, {"lize": {"live": {"on": False}, "avatarCheckedAt": "T", "avatar": "A", "zzz": 1}})
    assert list(merged["lize"]) == ["avatar", "avatarCheckedAt", "live", "zzz"]


def test_live_fails_is_kept_while_positive_and_removed_when_reset_to_zero():
    prev = {"lize": {"avatar": "A", "live": {"on": True, "checkedAt": "T0"}, "liveFails": 2}}
    failed = state.merge_status(prev, {"lize": {"liveFails": 3}})
    assert failed["lize"] == {"avatar": "A", "live": {"on": True, "checkedAt": "T0"}, "liveFails": 3}  # 실패: 이전 live·checkedAt 그대로
    recovered = state.merge_status(failed, {"lize": {"live": {"on": False, "checkedAt": "T1"}, "liveFails": 0}})
    assert recovered["lize"] == {"avatar": "A", "live": {"on": False, "checkedAt": "T1"}}  # 0이면 필드를 지운다 (파일에 0이 남지 않는다)


def test_live_fails_is_untouched_by_patches_that_do_not_mention_it():
    prev = {"lize": {"liveFails": 2, "live": {"on": True}}}
    merged = state.merge_status(prev, {"lize": {"avatar": "A"}, "tabi": {"live": {"on": False}}})
    assert merged["lize"]["liveFails"] == 2 and "liveFails" not in merged["tabi"]  # 치지직을 안 돌린 실행은 횟수를 건드리지 않는다


def test_a_zero_live_fails_from_a_patch_never_creates_the_field():
    assert state.merge_status({}, {"lize": {"liveFails": 0}}) == {"lize": {}}


def test_live_fails_sits_right_after_live_in_the_fixed_field_order():
    merged = state.merge_status({}, {"lize": {"uploads": "UU", "liveFails": 1, "live": {"on": False}, "avatar": "A"}})
    assert list(merged["lize"]) == ["avatar", "live", "liveFails", "uploads"]


def test_status_merge_does_not_mutate_inputs_and_is_idempotent():
    prev = {"lize": {"avatar": "A"}}
    patch = {"lize": {"live": {"on": True}}}
    before = copy.deepcopy((prev, patch))
    once = state.merge_status(prev, patch)
    assert (prev, patch) == before
    assert state.merge_status(once, patch) == once
    once["lize"]["live"]["on"] = False  # 결과를 고쳐도 입력 패치는 그대로 (깊은 복사)
    assert patch["lize"]["live"]["on"] is True
