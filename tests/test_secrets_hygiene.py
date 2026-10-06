"""커밋될 파일에 비밀(API 키·웹훅 URL)이 들어 있지 않은지 — "비밀을 코드·로그·커밋에 남기지 않는다"(CLAUDE.md)를 테스트로 고정.
검사 대상은 추적 중인 파일 + 아직 추적되지 않았지만 .gitignore에 걸리지 않는 파일(= 곧 커밋될 파일)이다. 커밋 전에 돌려도 의미가 있다.
실패 메시지에는 파일 경로만 나온다 — 비밀 값 자체는 어디에도 출력하지 않는다."""
import re
import subprocess

import pytest
from dotenv import dotenv_values

from conftest import ROOT

GOOGLE_API_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{35}")  # Google API 키 형식 (AIza + 35자)
WEBHOOK_URL = re.compile(r"https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[\w\-]{40,}")  # 실제 토큰은 60자 안팎 (테스트용 가짜 값은 더 짧다)


def committable_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git 저장소가 아니거나 git을 쓸 수 없음")
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p and (ROOT / p).is_file()]


def read(path):
    return path.read_bytes().decode("utf-8", errors="replace")


def rel(paths):
    return sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in paths)


def test_the_scan_actually_covers_the_repo():
    names = rel(committable_files())
    assert "main.py" in names and "updater/sources/youtube_api.py" in names and "tests/fixtures/youtube_api_playlist_lize.json" in names
    assert ".env" not in names and not any(n.startswith("out/") for n in names)  # 비밀 파일과 알림 중간 파일은 대상이 아니다


def test_no_google_api_key_shaped_string_in_committable_files():
    hits = [p for p in committable_files() if GOOGLE_API_KEY.search(read(p))]
    assert not hits, f"API 키 모양의 문자열이 든 파일: {rel(hits)}"


def test_no_discord_webhook_url_in_committable_files():
    hits = [p for p in committable_files() if WEBHOOK_URL.search(read(p))]
    assert not hits, f"웹훅 URL이 든 파일: {rel(hits)}"


def test_the_real_secrets_in_the_local_dotenv_are_not_in_committable_files():
    """내 PC의 .env에 든 실제 값이 커밋될 파일 어디에도 없는지 (값은 이 테스트 안에서만 쓰고 출력하지 않는다)."""
    env = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    secrets = [v.strip() for k, v in env.items() if k in ("YOUTUBE_API_KEY", "DISCORD_WEBHOOK_URL") and v and len(v.strip()) >= 8]
    if not secrets:
        pytest.skip("로컬 .env에 비밀 값이 없음")
    hits = [p for p in committable_files() if any(s in read(p) for s in secrets)]
    assert not hits, f"로컬 .env의 비밀 값이 든 파일: {rel(hits)}"


@pytest.mark.parametrize("path", [".env", "out/alerts.json"])
def test_secret_and_intermediate_files_are_git_ignored(path):
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    except OSError:
        pytest.skip("git을 쓸 수 없음")
    assert r.returncode == 0, f"{path}가 .gitignore에 없다"


def test_env_example_has_the_secret_names_with_empty_values():
    values = dotenv_values(ROOT / ".env.example")
    for name in ("DISCORD_WEBHOOK_URL", "YOUTUBE_API_KEY"):
        assert name in values and not values[name], f".env.example의 {name}은 이름만 있고 값은 비어 있어야 한다"
