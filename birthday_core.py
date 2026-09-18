from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
import re
import uuid

from lunardate import LunarDate

LUNAR_MONTH_NAMES = {
    1: "正月", 2: "二月", 3: "三月", 4: "四月", 5: "五月", 6: "六月",
    7: "七月", 8: "八月", 9: "九月", 10: "十月", 11: "冬月", 12: "腊月",
}
LUNAR_DAY_NAMES = {
    1: "初一", 2: "初二", 3: "初三", 4: "初四", 5: "初五", 6: "初六", 7: "初七", 8: "初八", 9: "初九", 10: "初十",
    11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五", 16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十",
    21: "廿一", 22: "廿二", 23: "廿三", 24: "廿四", 25: "廿五", 26: "廿六", 27: "廿七", 28: "廿八", 29: "廿九", 30: "三十",
}

CHINESE_MONTH_TO_INT = {
    "正": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "冬": 11, "十二": 12, "腊": 12,
}
CHINESE_DAY_TO_INT = {v: k for k, v in LUNAR_DAY_NAMES.items()}
CHINESE_DAY_TO_INT.update({"二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24,
                           "二十五": 25, "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29})


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class BirthdayRecord:
    id: str
    name: str
    calendar: str
    month: int
    day: int
    relation: str = ""
    birth_year: int | None = None
    leap_month: bool = False
    leap_policy: str = "normal"
    notes: str = ""
    reminders: list[int] | None = None
    created_at: str = ""
    updated_at: str = ""
    deleted: bool = False

    def __post_init__(self) -> None:
        if self.reminders is None:
            self.reminders = [7, 1, 0]
        if not self.created_at:
            self.created_at = now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    @classmethod
    def new(cls, *, name: str, calendar: str, month: int, day: int, relation: str = "",
            birth_year: int | None = None, leap_month: bool = False,
            leap_policy: str = "normal", notes: str = "") -> "BirthdayRecord":
        return cls(
            id=str(uuid.uuid4()), name=name.strip(), calendar=calendar, month=month, day=day,
            relation=relation.strip(), birth_year=birth_year, leap_month=leap_month,
            leap_policy=leap_policy, notes=notes.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "BirthdayRecord":
        known = {
            "id", "name", "calendar", "month", "day", "relation", "birth_year",
            "leap_month", "leap_policy", "notes", "reminders", "created_at", "updated_at", "deleted",
        }
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    def touch(self) -> None:
        self.updated_at = now_iso()


def lunar_label(month: int, day: int, leap: bool = False) -> str:
    prefix = "闰" if leap else ""
    return f"{prefix}{LUNAR_MONTH_NAMES.get(month, str(month) + '月')}{LUNAR_DAY_NAMES.get(day, str(day))}"


def original_birthday_label(record: BirthdayRecord) -> str:
    if record.calendar == "lunar":
        return "农历" + lunar_label(record.month, record.day, record.leap_month)
    return f"公历{record.month:02d}月{record.day:02d}日"


def _safe_solar_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        raise


def _safe_lunar_to_solar(lunar_year: int, month: int, day: int, leap: bool) -> date | None:
    try:
        return LunarDate(lunar_year, month, day, leap).to_solar_date()
    except ValueError:
        if day == 30:
            try:
                return LunarDate(lunar_year, month, 29, leap).to_solar_date()
            except ValueError:
                return None
        return None


def lunar_occurrence(record: BirthdayRecord, lunar_year: int) -> date | None:
    leap = record.leap_month
    if leap:
        try:
            actual_leap = LunarDate.leap_month_for_year(lunar_year)
        except ValueError:
            return None
        if actual_leap != record.month:
            if record.leap_policy == "skip":
                return None
            leap = False
    return _safe_lunar_to_solar(lunar_year, record.month, record.day, leap)


def next_occurrence(record: BirthdayRecord, today: date | None = None) -> date | None:
    today = today or date.today()
    if record.deleted:
        return None
    if record.calendar == "solar":
        for year in (today.year, today.year + 1, today.year + 2):
            try:
                candidate = _safe_solar_date(year, record.month, record.day)
            except ValueError:
                return None
            if candidate >= today:
                return candidate
        return None

    candidates: list[date] = []
    for lunar_year in range(today.year - 1, min(today.year + 4, 2100)):
        candidate = lunar_occurrence(record, lunar_year)
        if candidate and candidate >= today:
            candidates.append(candidate)
    return min(candidates) if candidates else None


def occurrences_between(record: BirthdayRecord, start_year: int, end_year: int) -> list[date]:
    if record.deleted:
        return []
    results: set[date] = set()
    if record.calendar == "solar":
        for year in range(start_year, end_year + 1):
            try:
                results.add(_safe_solar_date(year, record.month, record.day))
            except ValueError:
                pass
    else:
        for lunar_year in range(max(1900, start_year - 1), min(2099, end_year + 1) + 1):
            candidate = lunar_occurrence(record, lunar_year)
            if candidate and start_year <= candidate.year <= end_year:
                results.add(candidate)
    return sorted(results)


def validate_record(record: BirthdayRecord) -> None:
    if not record.name.strip():
        raise ValueError("姓名/称呼不能为空")
    if record.calendar not in {"solar", "lunar"}:
        raise ValueError("历法只能是公历或农历")
    if not 1 <= int(record.month) <= 12:
        raise ValueError("月份必须在 1~12 之间")
    max_day = 31 if record.calendar == "solar" else 30
    if not 1 <= int(record.day) <= max_day:
        raise ValueError(f"日期必须在 1~{max_day} 之间")
    if record.calendar == "solar":
        try:
            date(2024, int(record.month), int(record.day))
        except ValueError as exc:
            raise ValueError("这个公历日期不存在") from exc
    if record.birth_year is not None and not 1800 <= int(record.birth_year) <= 2200:
        raise ValueError("出生年份看起来不正确")


def merge_records(local: list[BirthdayRecord], incoming: list[BirthdayRecord]) -> list[BirthdayRecord]:
    merged = {r.id: r for r in local}
    for item in incoming:
        old = merged.get(item.id)
        if old is None or (item.updated_at or "") >= (old.updated_at or ""):
            merged[item.id] = item
    return list(merged.values())


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(records: list[BirthdayRecord], years: int = 20, today: date | None = None) -> str:
    today = today or date.today()
    end_year = min(today.year + max(1, years) - 1, 2099)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Family Birthday Manager//Offline Birthday Calendar//ZH-CN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:家庭生日",
    ]
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for record in records:
        if record.deleted:
            continue
        for occurrence in occurrences_between(record, today.year, end_year):
            next_day = occurrence + timedelta(days=1)
            summary = f"{record.name}生日｜{original_birthday_label(record)}"
            desc_parts = [f"原始生日：{original_birthday_label(record)}"]
            if record.relation:
                desc_parts.append(f"关系：{record.relation}")
            if record.birth_year:
                desc_parts.append(f"出生年份：{record.birth_year}")
            if record.notes:
                desc_parts.append(f"备注：{record.notes}")
            description = "\\n".join(_ics_escape(x) for x in desc_parts)
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{record.id}-{occurrence.strftime('%Y%m%d')}@familybirthday.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{occurrence.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{next_day.strftime('%Y%m%d')}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{description}",
                "CATEGORIES:Family,Birthday",
            ])
            for days in sorted(set(record.reminders or [7, 1, 0]), reverse=True):
                trigger = "-PT0M" if days == 0 else f"-P{int(days)}D"
                lines.extend([
                    "BEGIN:VALARM", f"TRIGGER:{trigger}", "ACTION:DISPLAY",
                    f"DESCRIPTION:{_ics_escape(record.name + '生日提醒')}", "END:VALARM",
                ])
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_quick(text: str) -> dict:
    raw = text.strip()
    if not raw:
        raise ValueError("请输入内容，例如：奶奶 农历腊月二十")

    calendar = "lunar" if any(k in raw for k in ("农历", "阴历")) else "solar"
    marker_match = re.search(r"(农历|阴历|公历|阳历)", raw)
    prefix = raw[: marker_match.start()].strip(" ，,：:") if marker_match else ""

    birth_year = None
    year_match = re.search(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2}|21\d{2})(?:年)?", raw)
    if year_match:
        birth_year = int(year_match.group(1))
        if not prefix:
            prefix = raw[: year_match.start()].strip(" ，,：:")

    leap_month = bool(re.search(r"闰\s*([正一二三四五六七八九十冬腊]{1,2})月", raw))
    month = day = None
    if calendar == "lunar":
        m = re.search(r"(?:农历|阴历)?\s*(?:闰)?\s*(正|一|二|三|四|五|六|七|八|九|十|十一|十二|冬|腊)月\s*(初[一二三四五六七八九十]|十[一二三四五六七八九]?|二十|二十[一二三四五六七八九]|廿[一二三四五六七八九]|三十)", raw)
        if m:
            month = CHINESE_MONTH_TO_INT[m.group(1)]
            day = CHINESE_DAY_TO_INT.get(m.group(2))
        if month is None:
            n = re.search(r"(?:农历|阴历)\s*(?:闰)?\s*(\d{1,2})\D+(\d{1,2})", raw)
            if n:
                month, day = int(n.group(1)), int(n.group(2))
    else:
        n = re.search(r"(?:公历|阳历)?\s*(?:(?:18\d{2}|19\d{2}|20\d{2}|21\d{2})[年\-/\.])?\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})(?:\s*日)?", raw)
        if n:
            month, day = int(n.group(1)), int(n.group(2))

    if month is None or day is None:
        raise ValueError("没识别出日期。示例：奶奶 农历腊月二十；妈妈 公历5月12日")

    if not prefix:
        prefix = re.split(r"农历|阴历|公历|阳历|\d{4}年|\d{1,2}月|闰?[正一二三四五六七八九十冬腊]{1,2}月", raw, maxsplit=1)[0].strip(" ，,：:")
    if not prefix:
        raise ValueError("没识别出姓名/称呼，请把称呼放在最前面")

    return {
        "name": prefix, "calendar": calendar, "month": month, "day": day,
        "birth_year": birth_year, "leap_month": leap_month,
    }
