from __future__ import annotations

import asyncio
from dataclasses import dataclass
import sys

from birthday_core import BirthdayRecord
from reminder_engine import ReminderSettings, build_reminder_occurrences


@dataclass
class ReminderRefreshResult:
    platform: str
    scheduled_count: int
    message: str


def is_windows_platform() -> bool:
    return sys.platform == "win32"


def refresh_windows_notifications(
    records: list[BirthdayRecord],
    settings: ReminderSettings,
) -> ReminderRefreshResult:
    if not is_windows_platform():
        return ReminderRefreshResult("windows", 0, "当前不是 Windows，已跳过 Windows 通知。")

    from windows_toasts import Toast, WindowsToaster

    toaster = WindowsToaster("家庭生日管理器")
    # We own only this toaster's schedules, so rebuilding is safer than trying
    # to diff dates after a birthday edit/delete.
    toaster.clear_scheduled_toasts()

    if not settings.enabled:
        return ReminderRefreshResult("windows", 0, "Windows 本地提醒已关闭。")

    occurrences = build_reminder_occurrences(records, settings)
    for item in occurrences:
        toast = Toast([item.title, item.body])
        toaster.schedule_toast(toast, item.remind_at)

    return ReminderRefreshResult(
        "windows",
        len(occurrences),
        f"已向 Windows 注册 {len(occurrences)} 条本地生日提醒。",
    )


def show_windows_test_notification() -> None:
    if not is_windows_platform():
        raise RuntimeError("测试通知仅适用于 Windows。")

    from windows_toasts import Toast, WindowsToaster

    toaster = WindowsToaster("家庭生日管理器")
    toaster.show_toast(Toast(["🎂 家庭生日管理器", "这是一条本地测试提醒。"]))


class AndroidReminderBackend:
    def __init__(self):
        from flet_android_notifications import FletAndroidNotifications

        self.service = FletAndroidNotifications()

    async def request_permissions(self) -> bool:
        return bool(await self.service.request_permissions())

    async def notifications_enabled(self) -> bool:
        return bool(await self.service.are_notifications_enabled())

    async def can_schedule_exact(self) -> bool:
        return bool(await self.service.can_schedule_exact_notifications())

    async def request_exact_alarm_permission(self) -> bool:
        return bool(await self.service.request_exact_alarm_permission())

    async def pending_notifications(self) -> list[dict]:
        return list(await self.service.get_pending_notifications())

    async def refresh(
        self,
        records: list[BirthdayRecord],
        settings: ReminderSettings,
    ) -> ReminderRefreshResult:
        # All birthday schedules belong to this app. Rebuild after any data edit
        # so deleted/changed birthdays cannot leave stale alarms behind.
        await self.service.cancel_all()

        if not settings.enabled:
            return ReminderRefreshResult("android", 0, "Android 本地提醒已关闭。")

        occurrences = build_reminder_occurrences(records, settings)
        exact_allowed = await self.can_schedule_exact()
        schedule_mode = "exact_allow_while_idle" if exact_allowed else "inexact_allow_while_idle"

        for item in occurrences:
            await self.service.schedule_notification(
                notification_id=item.notification_id,
                title=item.title,
                body=item.body,
                scheduled_time=item.remind_at,
                payload=item.record_id,
                channel_id="birthday_reminders",
                channel_name="生日提醒",
                channel_description="家庭生日管理器的本地生日提醒",
                schedule_mode=schedule_mode,
            )

        mode_text = "精确后台模式" if exact_allowed else "非精确兼容模式"
        return ReminderRefreshResult(
            "android",
            len(occurrences),
            f"已向 Android 注册 {len(occurrences)} 条本地生日提醒（{mode_text}）。",
        )

    async def show_test_notification(self) -> None:
        await self.service.show_notification(
            notification_id=2147483000,
            title="🎂 家庭生日管理器",
            body="这是一条本地测试提醒。",
            channel_id="birthday_reminders",
            channel_name="生日提醒",
            channel_description="家庭生日管理器的本地生日提醒",
        )


async def refresh_platform_notifications(
    platform: str,
    records: list[BirthdayRecord],
    settings: ReminderSettings,
    android_backend: AndroidReminderBackend | None = None,
) -> ReminderRefreshResult:
    platform = platform.lower()
    if "windows" in platform:
        # Keep scheduling on the app event loop. It is a short, OS-native
        # registration operation and avoids leaving an unkillable worker thread
        # behind if the user closes the Windows app mid-refresh.
        return refresh_windows_notifications(records, settings)
    if "android" in platform:
        if android_backend is None:
            raise RuntimeError("Android 通知服务尚未初始化。")
        return await android_backend.refresh(records, settings)
    return ReminderRefreshResult(platform, 0, "当前平台暂不支持应用自身的本地通知；仍可使用 ICS。")
