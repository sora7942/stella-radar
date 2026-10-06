"""테스트용 가짜 YouTube Data API: 실제 응답 픽스처로 channels.list·playlistItems.list에 답한다. test_youtube_api.py와 test_main.py가 함께 쓴다.

http.get 대용으로 쓰이므로 (url, headers=...)를 받는다. calls에 (url, 넘어온 인자)를 기록해서, 키가 헤더로만 갔는지 검사할 수 있다."""
import json
from urllib.parse import parse_qs, urlparse

import requests

from conftest import FIXTURES, make_response

LIZE, KANGJI, OFFICIAL = "UC7-m6jQLinZQWIbwm9W-1iw", "UCIVFv8AiQLqM9oLHTixrNYw", "UC2b4WRE5BZ6SIUWBeJU8rwg"
KEY = "TESTKEY-not-a-real-key-0123456789"  # 'AIza…' 모양이 아니어야 저장소 스캔 테스트(test_secrets_hygiene)와 부딪히지 않는다


def fx(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def uploads_of(channel_id: str) -> str:
    return "UU" + channel_id[2:]


def http_error(status: int, body) -> requests.HTTPError:
    """실제 requests 오류처럼 메시지에 (키가 든) URL을 넣는다 — 우리 코드가 이 메시지를 쓰지 않는지 시험하려는 것."""
    if isinstance(body, str) and body.endswith(".json"):
        body = fx(body)
    payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return requests.HTTPError(f"{status} Error for url: https://www.googleapis.com/youtube/v3/x?key={KEY}", response=make_response(status, payload))


EMPTY_PLAYLIST = {"kind": "youtube#playlistItemListResponse", "items": [], "pageInfo": {"totalResults": 0, "resultsPerPage": 15}}


class FakeApi:
    """fail[("channels", None)] 또는 fail[("playlistItems", 재생목록 ID)]에 예외를 넣으면 그 호출이 실패한다.
    quota_after=N이면 playlistItems 호출 N번까지는 성공하고 그다음부터 할당량 초과(403 quotaExceeded).
    reject_after=N이면 같은 식으로 N번 뒤부터 키 거부(403 forbidden — 실제 '키 없음' 응답)."""

    def __init__(self, *, playlists=None, fail=None, quota_after=None, reject_after=None, missing_channels=(), stale=None):
        self.calls: list[tuple[str, dict]] = []
        self.playlists = {
            uploads_of(LIZE): fx("youtube_api_playlist_lize.json"),
            uploads_of(KANGJI): fx("youtube_api_playlist_kangji.json"),
            uploads_of(OFFICIAL): fx("youtube_api_playlist_official.json"),
            **(playlists or {}),
        }
        self.fail = fail or {}
        self.quota_after, self.reject_after, self.missing_channels = quota_after, reject_after, set(missing_channels)
        self.stale = set(stale or ())  # 이 재생목록 ID는 playlistNotFound (낡은 캐시 시험)
        self.playlist_calls = 0

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        endpoint = u.path.rsplit("/", 1)[1]
        if endpoint == "channels":
            if ("channels", None) in self.fail:
                raise self.fail[("channels", None)]
            real = {i["id"]: i for i in fx("youtube_api_channels.json")["items"]}
            items = [
                real.get(cid) or {"kind": "youtube#channel", "id": cid, "contentDetails": {"relatedPlaylists": {"uploads": uploads_of(cid)}}}
                for cid in q["id"].split(",") if cid not in self.missing_channels
            ]
            return make_response(200, json.dumps({"kind": "youtube#channelListResponse", "pageInfo": {"totalResults": len(items)}, "items": items}))
        if endpoint == "playlistItems":
            self.playlist_calls += 1
            if self.quota_after is not None and self.playlist_calls > self.quota_after:
                raise http_error(403, "youtube_api_error_quota.json")
            if self.reject_after is not None and self.playlist_calls > self.reject_after:
                raise http_error(403, "youtube_api_error_nokey.json")
            pid = q["playlistId"]
            if pid in self.stale:
                raise http_error(404, "youtube_api_error_playlist_not_found.json")
            if ("playlistItems", pid) in self.fail:
                raise self.fail[("playlistItems", pid)]
            return make_response(200, json.dumps(self.playlists.get(pid, EMPTY_PLAYLIST)))
        raise AssertionError(f"예상 밖의 API 호출: {url}")

    def endpoints(self) -> list[str]:
        return [urlparse(u).path.rsplit("/", 1)[1] for u, _ in self.calls]

    def query(self, n: int) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.calls[n][0]).query).items()}
