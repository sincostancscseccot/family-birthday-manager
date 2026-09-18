from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
import hashlib

from birthday_core import BirthdayRecord, occurrences_between, original_birthday_label


@dataclass
class ReminderSettings:
    enabled: bool = False
    hour: int = 9
    minute: int = 0
    horizon_years: int = 3

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReminderSettings":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            hour=int(data.get("hour", 9)),
            minute=int(data.get("minute", 0)),
            horizon_years=max(1, min(5, int(data.get("horizon_years", 3)))),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ValueError("提醒小时必须在 0~23 之间")
        if not 0 <= self.minute <= 59:
            raise ValueError("提醒分钟必须在 0~59 之间")
        if not 1 <= self.horizon_years <= 5:
            raise ValueError("本地通知预排范围必须在 1~5 年之间")


@dataclass(frozen=True)
class ReminderOccurrence:
    notification_id: int
    record_id: str
    name: str
    birthday_date: datetime
    remind_at: datetime
    days_before: int
    title: str
    body: str


def _notification_id(record_id: str, birthday_yyyymmdd: str, days_before: int) -> int:
    raw = f"{record_id}|{birthday_yyyymmdd}|{days_before}".encode("utf-8")
    # Android notification IDs are signed 32-bit ints; keep 0 unused.
    value = int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") & 0x7FFFFFFF
    return value or 1


def _message(record: BirthdayRecord, birthday_dt: datetime, days_before: int) -> tuple[str, str]:
    if days_before == 0:
        title = f"🎂 今天是{record.name}的生日"
    elif days_before == 1:
        title = f"🎂 明天是{record.name}的生日"
    else:
        title = f"🎂 {days_before}天后是{record.name}的生日"

    body = f"{birthday_dt:%Y年%m月%d日} · {original_birthday_label(record)}"
    if record.relation:
        body += f" · {record.relation}"
    return title, body


def build_reminder_occurrences(
    records: list[BirthdayRecord],
    settings: ReminderSettings,
    now: datetime | None = None,
) -> list[ReminderOccurrence]:
    settings.validate()
    now = now or datetime.now()
    if not settings.enabled:
        return []

    start_year = now.year
    end_year = min(2099, now.year + settings.horizon_years)
    result: list[ReminderOccurrence] = []

    for record in records:
        if record.deleted:
            continue

        reminders = sorted({int(x) for x in (record.reminders or [7, 1, 0]) if int(x) >= 0}, reverse=True)
        for birthday in occurrences_between(record, start_year, end_year):
            birthday_dt = datetime.combine(birthday, time(settings.hour, settings.minute))
            for days_before in reminders:
                remind_at = birthday_dt - timedelta(days=days_before)
                if remind_at <= now:
                    continue
                title, body = _message(record, birthday_dt, days_before)
                result.append(
                    ReminderOccurrence(
                        notification_id=_notification_id(record.id, birthday.strftime("%Y%m%d"), days_before),
                        record_id=record.id,
                        name=record.name,
                        birthday_date=birthday_dt,
                        remind_at=remind_at,
                        days_before=days_before,
                        title=title,
                        body=body,
                    )
                )

    result.sort(key=lambda item: (item.remind_at, item.name, item.days_before))
    return result
