from datetime import date

from birthday_core import BirthdayRecord, next_occurrence, parse_quick, original_birthday_label


def test_quick_lunar():
    x = parse_quick("奶奶 农历腊月二十")
    assert x["name"] == "奶奶"
    assert x["calendar"] == "lunar"
    assert x["month"] == 12 and x["day"] == 20


def test_quick_solar():
    x = parse_quick("妈妈 公历5月12日")
    assert x["name"] == "妈妈"
    assert x["calendar"] == "solar"
    assert x["month"] == 5 and x["day"] == 12


def test_solar_next():
    r = BirthdayRecord.new(name="A", calendar="solar", month=10, day=1)
    assert next_occurrence(r, date(2026, 9, 18)) == date(2026, 10, 1)


def test_label():
    r = BirthdayRecord.new(name="A", calendar="lunar", month=12, day=20)
    assert original_birthday_label(r) == "农历腊月二十"
