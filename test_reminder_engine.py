from datetime import datetime

from birthday_core import BirthdayRecord
from reminder_engine import ReminderSettings, build_reminder_occurrences


def test_build_three_default_reminders():
    record = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    settings = ReminderSettings(enabled=True, hour=9, minute=0, horizon_years=1)
    items = build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0))

    first_year = [x for x in items if x.birthday_date.year == 2026]
    assert [x.days_before for x in first_year] == [7, 1, 0]
    assert first_year[0].remind_at == datetime(2026, 9, 24, 9, 0)
    assert first_year[1].remind_at == datetime(2026, 9, 30, 9, 0)
    assert first_year[2].remind_at == datetime(2026, 10, 1, 9, 0)


def test_disabled_produces_no_reminders():
    record = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    settings = ReminderSettings(enabled=False)
    assert build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0)) == []


def test_deleted_record_not_scheduled():
    record = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    record.deleted = True
    settings = ReminderSettings(enabled=True)
    assert build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0)) == []


def test_notification_ids_are_stable_and_nonzero():
    record = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    settings = ReminderSettings(enabled=True)
    a = build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0))
    b = build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0))
    assert [x.notification_id for x in a] == [x.notification_id for x in b]
    assert all(x.notification_id > 0 for x in a)


def test_explicit_empty_reminders_stays_empty():
    record = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    record.reminders = []
    settings = ReminderSettings(enabled=True)
    assert build_reminder_occurrences([record], settings, datetime(2026, 9, 1, 12, 0)) == []
