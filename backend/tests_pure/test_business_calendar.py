"""
BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1: app.core.business_calendar.resolve_business_date is
framework-free (no sqlalchemy/fastapi/pydantic import - see the module's own docstring), so it's
exercised here with plain unittest, no DB, per §2.1's determinism-boundary discipline applied to
the one function in this codebase now permitted to read a real clock.
"""
from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta, timezone

from app.core.business_calendar import InvalidBusinessTimezoneError, resolve_business_date


class TestPositiveAndNegativeOffsetDivergeAtMidnight(unittest.TestCase):
    """The whole point of this module: the same UTC instant must resolve to a different calendar
    date in a positive-offset zone (already past midnight locally) than in a negative-offset zone
    (not yet at midnight locally) - proving the resolver actually converts through zoneinfo
    rather than just returning the UTC date unchanged."""

    def test_same_instant_is_already_tomorrow_in_a_positive_offset_zone(self):
        # 23:30 UTC + Tokyo's fixed UTC+9 = 08:30 the next day, local.
        instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)
        self.assertEqual(resolve_business_date("Asia/Tokyo", utc_instant=instant), date(2026, 3, 16))

    def test_same_instant_is_still_today_in_a_negative_offset_zone(self):
        # The identical instant, in Los Angeles (UTC-8 in March, before US DST) - still the 15th.
        instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)
        self.assertEqual(resolve_business_date("America/Los_Angeles", utc_instant=instant), date(2026, 3, 15))

    def test_utc_zone_itself_matches_the_instants_own_calendar_date(self):
        instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)
        self.assertEqual(resolve_business_date("UTC", utc_instant=instant), date(2026, 3, 15))

    def test_two_zones_genuinely_differ_for_the_same_instant(self):
        instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)
        tokyo_date = resolve_business_date("Asia/Tokyo", utc_instant=instant)
        la_date = resolve_business_date("America/Los_Angeles", utc_instant=instant)
        self.assertNotEqual(tokyo_date, la_date)


class TestRejectsInvalidInputExplicitly(unittest.TestCase):
    def test_naive_instant_is_rejected_not_silently_treated_as_utc(self):
        # Built from an aware instant and stripped, rather than a bare datetime(...) call, so
        # this deliberately-naive fixture doesn't itself trip Ruff's DTZ001.
        naive_instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC).replace(tzinfo=None)
        with self.assertRaises(InvalidBusinessTimezoneError):
            resolve_business_date("UTC", utc_instant=naive_instant)

    def test_aware_but_non_utc_instant_is_rejected_not_silently_converted(self):
        non_utc_aware = datetime(2026, 3, 15, 23, 30, tzinfo=timezone(timedelta(hours=2)))
        with self.assertRaises(InvalidBusinessTimezoneError):
            resolve_business_date("UTC", utc_instant=non_utc_aware)

    def test_unknown_timezone_name_is_rejected_not_silently_defaulted(self):
        instant = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        with self.assertRaises(InvalidBusinessTimezoneError):
            resolve_business_date("Not/AZone", utc_instant=instant)

    def test_empty_timezone_name_is_rejected(self):
        instant = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        with self.assertRaises(InvalidBusinessTimezoneError):
            resolve_business_date("", utc_instant=instant)


class TestDefaultInstantIsTheRealCurrentUtcInstant(unittest.TestCase):
    """Not a determinism test (that's what utc_instant is for) - just confirms the no-argument
    path returns a real, correctly-typed date rather than raising or returning something else."""

    def test_omitting_utc_instant_returns_a_date_instance(self):
        result = resolve_business_date("Africa/Johannesburg")
        self.assertIsInstance(result, date)


if __name__ == "__main__":
    unittest.main()
