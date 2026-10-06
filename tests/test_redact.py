"""비밀 값 가림(마지막 방어선). 1차 방어(비밀을 메시지에 넣지 않기)는 각 모듈 테스트에서 확인한다."""
import io
import logging

import pytest

from updater import redact

SECRET = "TESTKEY-not-a-real-key-0123456789"


def make_logger(name, stream):
    logger = logging.getLogger(name)
    logger.handlers = [h for h in logger.handlers if False]
    handler = logging.StreamHandler(stream)
    handler.setFormatter(redact.RedactingFormatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


def test_registered_secrets_are_masked_everywhere_they_appear():
    redact.register(SECRET)
    assert redact.mask(f"a {SECRET} b {SECRET}") == "a *** b ***"
    assert redact.mask("아무 비밀도 없는 문장") == "아무 비밀도 없는 문장"


def test_unregistered_text_is_untouched_and_clear_forgets():
    assert redact.mask(f"x {SECRET}") == f"x {SECRET}"
    redact.register(SECRET)
    redact.clear()
    assert redact.mask(SECRET) == SECRET


@pytest.mark.parametrize("value", [None, "", "   ", "short"])
def test_empty_or_too_short_values_are_not_registered(value):
    redact.register(value)
    assert redact.mask("short and empty words stay") == "short and empty words stay"


def test_longer_secrets_are_masked_before_their_prefixes():
    redact.register(SECRET)
    redact.register(SECRET + "-longer")
    assert redact.mask(f"v {SECRET}-longer") == "v ***"


def test_whitespace_around_a_secret_is_ignored_when_registering():
    redact.register(f"  {SECRET}\n")
    assert redact.mask(SECRET) == "***"


def test_formatter_masks_messages_and_arguments():
    redact.register(SECRET)
    stream = io.StringIO()
    make_logger("t.redact.msg", stream).warning("실패: %s / %s", SECRET, "ok")
    assert stream.getvalue() == "WARNING 실패: *** / ok\n"


def test_formatter_masks_traceback_text_too():
    redact.register(SECRET)
    stream = io.StringIO()
    log = make_logger("t.redact.tb", stream)
    try:
        raise RuntimeError(f"url?key={SECRET}")
    except RuntimeError:
        log.error("터짐", exc_info=True)
    out = stream.getvalue()
    assert "터짐" in out and "RuntimeError" in out and SECRET not in out and "url?key=***" in out


def test_configure_logging_installs_the_redacting_formatter_when_no_handler_exists(monkeypatch):
    root = logging.getLogger()
    saved, saved_level = root.handlers[:], root.level
    try:
        root.handlers = []
        redact.configure_logging()
        assert any(isinstance(h.formatter, redact.RedactingFormatter) for h in root.handlers)
    finally:
        root.handlers, root.level = saved, saved_level
