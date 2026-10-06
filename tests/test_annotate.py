"""GitHub Actions 주석(::warning::). Actions가 아니면 아무것도 내지 않는다."""
import pytest

from updater import annotate, redact

ON = {"GITHUB_ACTIONS": "true"}


def test_prints_a_warning_command_only_on_github_actions(capsys):
    assert annotate.warning("제목", "내용", environ=ON) is True
    assert capsys.readouterr().out == "::warning title=제목::내용\n"
    assert annotate.warning("제목", "내용", environ={}) is False and capsys.readouterr().out == ""


@pytest.mark.parametrize("value", ["false", "", "1", "TRUE"])
def test_only_the_exact_value_true_counts_as_actions(value, capsys):
    assert annotate.warning("t", "m", environ={"GITHUB_ACTIONS": value}) is False and capsys.readouterr().out == ""


def test_newlines_and_percent_signs_cannot_break_the_command(capsys):
    annotate.warning("a:b,c", "첫 줄\n::error::가짜 명령\r100%", environ=ON)
    out = capsys.readouterr().out
    assert out == "::warning title=a%3Ab%2Cc::첫 줄%0A::error::가짜 명령%0D100%25\n"
    assert out.count("\n") == 1  # 한 줄이다


def test_registered_secrets_are_masked(capsys):
    redact.register("TESTKEY-not-a-real-key-0123456789")
    annotate.warning("t", "oops TESTKEY-not-a-real-key-0123456789 leaked", environ=ON)
    assert capsys.readouterr().out == "::warning title=t::oops *** leaked\n"
