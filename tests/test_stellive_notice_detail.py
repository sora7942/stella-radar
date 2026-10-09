"""공지 상세 본문 추출 (기능 3-0에서 확인한 규칙을 실제 응답 픽스처로 고정한다). 네트워크 없음."""
import pytest
import requests

from conftest import FIXTURES, FakeGet, make_response
from updater import config
from updater.sources import stellive_notice_detail as detail


def load(name):
    return (FIXTURES / name).read_bytes()


def test_popup_notice_body_has_the_dates_times_and_place_as_text():
    text = detail.parse_body(load("stellive_news_detail_13905.html"))
    assert detail.char_count(text) == 3136  # 3-0에서 센 3137자에서 이모지 안의 제로폭 결합 문자(ZWJ) 1개를 뺀 값
    for expected in ("2026년 10월 12일 (월) 오후 8시", "2026년 10월 23일 (금) ~ 11월 1일 (일)", "서울특별시 광진구 광나루로 441",
                     "오전 10시 ~ 오후 8시", "1회차: 10:00 ~ 11:00", "10회차: 19:00 ~ 20:00"):
        assert expected in text, expected
    assert "26.10.23 – 26.11.05" in text  # 같은 본문 안의 별건 일정(포토이즘)도 그대로 들어 있다


def test_only_the_body_container_is_read_not_the_board_list_that_the_detail_page_also_contains():
    """상세 페이지에는 공지 목록이 같이 들어 있다 — 목록 첫 항목의 제목이 본문에 섞이면 안 된다 (픽스처에도 목록 앞 2개가 남아 있다)."""
    raw = load("stellive_news_detail_13905.html").decode("utf-8")
    assert "2026 아라하시 타비 생일 한정 굿즈 판매 마감 임박 안내" in raw  # 함정이 픽스처에 실제로 있다
    text = detail.parse_body(raw.encode("utf-8"))
    assert "아라하시 타비" not in text and "BeforeDocument" not in text


def test_goods_notice_body_has_the_sales_deadline_as_text():
    text = detail.parse_body(load("stellive_news_detail_goods_14073.html"))
    assert "2026년 10월 7일(수)" in text and "23시 59분까지" in text
    assert detail.char_count(text) >= config.EVENTS_NO_TEXT_CHARS


def test_image_only_notice_has_no_text_below_the_threshold():
    text = detail.parse_body(load("stellive_news_detail_imageonly_13838.html"))
    assert text == "" and detail.char_count(text) < config.EVENTS_NO_TEXT_CHARS


def test_missing_container_is_a_parse_error_not_an_empty_body():
    """차단 페이지·레이아웃 변경을 '본문 없음(no_text)'으로 오해하지 않는다."""
    with pytest.raises(detail.BodyParseError):
        detail.parse_body(b"<html><body><p>Access denied</p></body></html>")


def test_lines_are_trimmed_blank_lines_dropped_and_invisible_characters_removed():
    html = ("<div class='xe_content'><p>  첫   줄" + chr(0x200b) + " </p><p></p><p>" + chr(0xa0) + "</p><p>둘째&nbsp;줄</p></div>").encode("utf-8")
    assert detail.parse_body(html) == "첫 줄\n둘째 줄"


def test_page_without_a_charset_meta_is_still_read_as_utf8():
    """응답 바이트를 그대로 파서에 넘기면 메타가 없을 때 인코딩을 잘못 추측해 한글이 깨진다 — 깨진 본문이 모델로 가면 안 된다."""
    assert detail.parse_body("<div class='xe_content'><p>팝업 안내</p></div>".encode("utf-8")) == "팝업 안내"


def test_char_count_ignores_whitespace():
    assert detail.char_count(" a b\n c\t") == 3


def test_fetch_body_requests_the_notice_url_through_the_injected_get():
    get = FakeGet(make_response(200, load("stellive_news_detail_goods_14073.html")))
    assert "23시 59분까지" in detail.fetch_body("14073", get=get)
    assert get.calls == [config.NEWS_ITEM_URL.format(number="14073")]


def test_fetch_body_lets_http_errors_through_for_the_caller_to_classify():
    with pytest.raises(requests.HTTPError) as e:
        detail.fetch_body("1", get=FakeGet(make_response(404, "no")))
    assert e.value.response.status_code == 404
