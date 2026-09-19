from __future__ import annotations

import json
import os
from pathlib import Path

from birthday_core import BirthdayRecord, merge_records
from reminder_engine import ReminderSettings

SCHEMA_VERSION = 1


def data_dir() -> Path:
    root = Path(os.environ.get("FLET_APP_STORAGE_DATA", "."))
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_file() -> Path:
    return data_dir() / "family_birthdays.json"


def load_records() -> list[BirthdayRecord]:
    path = data_file()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [BirthdayRecord.from_dict(x) for x in payload.get("records", [])]
    except Exception:
        # Keep the damaged file for manual recovery; start safely with an empty view.
        return []


def save_records(records: list[BirthdayRecord]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "records": [r.to_dict() for r in records],
    }
    target = data_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def export_backup_bytes(records: list[BirthdayRecord]) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "records": [r.to_dict() for r in records],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def import_backup_bytes(raw: bytes, local: list[BirthdayRecord]) -> list[BirthdayRecord]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("备份文件不是有效的 JSON") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("备份版本不兼容")
    incoming = [BirthdayRecord.from_dict(x) for x in payload.get("records", [])]
    return merge_records(local, incoming)


def reminder_settings_file() -> Path:
    return data_dir() / "reminder_settings.json"


def load_reminder_settings() -> ReminderSettings:
    path = reminder_settings_file()
    if not path.exists():
        return ReminderSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ReminderSettings.from_dict(payload)
    except Exception:
        return ReminderSettings()


def save_reminder_settings(settings: ReminderSettings) -> None:
    settings.validate()
    target = reminder_settings_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
