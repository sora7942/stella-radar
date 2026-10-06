"""모든 테스트에서 실제 네트워크 접근을 막는다 (CLAUDE.md: 테스트에서 실제 네트워크·디스코드 호출 금지).
실수로 실호출하면 즉시 실패한다. HTTP가 필요한 코드는 get 함수를 주입해서 시험한다."""
import json
import socket
from pathlib import Path

import pytest
import requests

from updater import config

ROOT =Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise NetworkBlocked("테스트에서 실제 네트워크 호출은 금지입니다")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def _alerts_file_in_tmp(monkeypatch, tmp_path):
    """알림 파일(out/alerts.json)은 테스트마다 임시 폴더로 돌린다 — 테스트가 저장소의 실제 out/을 건드리지 못하게."""
    monkeypatch.setattr(config, "ALERTS_FILE", tmp_path / "out" / "alerts.json")


@pytest.fixture(autouse=True)
def _no_webhook_in_env(monkeypatch):
    """개발 PC에 DISCORD_WEBHOOK_URL이 설정돼 있어도 테스트가 그 값을 보지 못하게 한다 (실제 발송 방지).
    웹훅이 필요한 테스트는 스스로 가짜 값을 넣는다."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)


@pytest.fixture(scope="session")
def members():
    """저장소의 실제 members.json (태깅 사전의 원천)."""
    return json.loads((ROOT / "site" / "data" / "members.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()


def make_response(status: int = 200, body: bytes | str = b"") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode("utf-8") if isinstance(body, str) else body
    resp.url = "https://example.invalid/"
    return resp


class FakeGet:
    """http.get 대용. 호출 순서대로 미리 정한 결과(Response 또는 예외)를 돌려주고, 4xx/5xx는 실제 get처럼 HTTPError로 던진다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        if out.status_code >= 400:
            raise requests.HTTPError(f"{out.status_code} for {url}", response=out)
        return out
