from datetime import datetime, timezone

import pytest

from updater import timeutil


def test_utc_to_kst_iso():
    assert timeutil.to_kst_iso("2026-10-04T06:44:08+00:00") == "2026-10-04T15:44:08+09:00"


def test_kst_stays_kst_and_crosses_midnight():
    assert timeutil.to_kst_iso("2026-10-04T20:00:00+00:00") == "2026-10-05T05:00:00+09:00"
    assert timeutil.to_kst_iso(datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)) == "2026-10-04T10:00:00+09:00"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        timeutil.to_kst_iso("2026-10-04T06:44:08")


def test_parse_kst_date_only_is_midnight_kst():
    dt = timeutil.parse_kst("2026-10-04")
    assert dt.isoformat() == "2026-10-04T00:00:00+09:00"


def test_now_kst_is_aware_and_kst():
    assert timeutil.now_kst().utcoffset().total_seconds() == 9 * 3600
