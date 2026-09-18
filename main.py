from __future__ import annotations

from datetime import date
import asyncio
import threading

import flet as ft

from birthday_core import (
    BirthdayRecord,
    build_ics,
    next_occurrence,
    original_birthday_label,
    parse_quick,
    validate_record,
)
from storage import export_backup_bytes, import_backup_bytes, load_records, save_records
from lan_sync import LanSyncServer, qr_png_base64, sync_with_peer


async def main(page: ft.Page):
    page.title = "家庭生日管理器"
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO
    page.theme_mode = ft.ThemeMode.SYSTEM

    records = load_records()
    records_lock = threading.RLock()
    lan_server: LanSyncServer | None = None
    status = ft.Text("", size=13)
    quick = ft.TextField(
        label="快速添加",
        hint_text="例如：奶奶 农历腊月二十 / 妈妈 公历5月12日",
        expand=True,
    )
    birthday_list = ft.Column(spacing=8)

    def active_records():
        with records_lock:
            return [r for r in records if not r.deleted]

    def set_status(message: str):
        status.value = message
        page.update()

    def save_all():
        with records_lock:
            save_records(records)

    def backup_bytes() -> bytes:
        with records_lock:
            return export_backup_bytes(records)

    def merge_lan_backup(raw: bytes) -> bytes:
        with records_lock:
            merged = import_backup_bytes(raw, records)
            records.clear()
            records.extend(merged)
            save_records(records)
            return export_backup_bytes(records)

    def record_by_id(record_id: str) -> BirthdayRecord | None:
        return next((r for r in records if r.id == record_id), None)

    def render_list():
        birthday_list.controls.clear()
        today = date.today()
        items = []
        for record in active_records():
            nxt = next_occurrence(record, today)
            delta = (nxt - today).days if nxt else 10**9
            items.append((delta, record, nxt))
        items.sort(key=lambda x: (x[0], x[1].name))

        if not items:
            birthday_list.controls.append(
                ft.Container(
                    content=ft.Text("还没有生日记录。可以直接在上方输入“奶奶 农历腊月二十”。"),
                    padding=20,
                    alignment=ft.Alignment.CENTER,
                )
            )
        for days_left, record, nxt in items:
            subtitle = original_birthday_label(record)
            if nxt:
                subtitle += f"  →  {nxt:%Y-%m-%d}"
                subtitle += "  ·  今天" if days_left == 0 else f"  ·  还有 {days_left} 天"
            if record.relation:
                subtitle += f"  ·  {record.relation}"
            birthday_list.controls.append(
                ft.Card(
                    content=ft.ListTile(
                        leading=ft.CircleAvatar(content=ft.Text(record.name[:1])),
                        title=ft.Text(record.name, weight=ft.FontWeight.BOLD),
                        subtitle=ft.Text(subtitle),
                        trailing=ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.EDIT_OUTLINED,
                                    tooltip="编辑",
                                    on_click=lambda e, rid=record.id: open_editor(rid),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    tooltip="删除",
                                    on_click=lambda e, rid=record.id: delete_record(rid),
                                ),
                            ],
                            tight=True,
                        ),
                    )
                )
            )
        page.update()

    def delete_record(record_id: str):
        record = record_by_id(record_id)
        if not record:
            return
        record.deleted = True
        record.touch()
        save_all()
        set_status(f"已删除：{record.name}（离线同步时会保留删除标记）")
        render_list()

    def open_editor(record_id: str | None = None, preset: dict | None = None):
        existing = record_by_id(record_id) if record_id else None
        preset = preset or {}

        name = ft.TextField(label="姓名/称呼 *", value=(existing.name if existing else preset.get("name", "")), autofocus=True)
        relation = ft.TextField(label="关系（可选）", hint_text="如：妈妈、舅舅、表姐", value=(existing.relation if existing else ""))
        calendar = ft.Dropdown(
            label="历法 *",
            value=(existing.calendar if existing else preset.get("calendar", "solar")),
            options=[
                ft.DropdownOption(key="solar", text="公历 / 阳历"),
                ft.DropdownOption(key="lunar", text="农历 / 阴历"),
            ],
        )
        month = ft.TextField(
            label="月 *",
            value=str(existing.month if existing else preset.get("month", "")),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )
        day = ft.TextField(
            label="日 *",
            value=str(existing.day if existing else preset.get("day", "")),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )
        birth_year = ft.TextField(
            label="出生年份（可选）",
            value=str(existing.birth_year or "") if existing else (str(preset.get("birth_year")) if preset.get("birth_year") else ""),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        leap_month = ft.Checkbox(
            label="这是闰月生日",
            value=(existing.leap_month if existing else bool(preset.get("leap_month", False))),
        )
        leap_policy = ft.Dropdown(
            label="没有对应闰月的年份",
            value=(existing.leap_policy if existing else "normal"),
            options=[
                ft.DropdownOption(key="normal", text="按普通同月同日过"),
                ft.DropdownOption(key="skip", text="该年不过 / 不生成提醒"),
            ],
        )
        notes = ft.TextField(label="备注（可选）", value=(existing.notes if existing else ""), multiline=True, min_lines=2, max_lines=4)
        form_error = ft.Text("", color=ft.Colors.ERROR)

        def refresh_lunar_fields():
            is_lunar = calendar.value == "lunar"
            leap_month.visible = is_lunar
            leap_policy.visible = is_lunar and bool(leap_month.value)
            page.update()

        def on_calendar_select(e):
            refresh_lunar_fields()

        def on_leap_change(e):
            refresh_lunar_fields()

        calendar.on_select = on_calendar_select
        leap_month.on_change = on_leap_change

        async def do_save(e):
            try:
                m = int(month.value or 0)
                d = int(day.value or 0)
                by = int(birth_year.value) if birth_year.value and birth_year.value.strip() else None
                if existing:
                    existing.name = name.value.strip()
                    existing.relation = relation.value.strip()
                    existing.calendar = calendar.value
                    existing.month = m
                    existing.day = d
                    existing.birth_year = by
                    existing.leap_month = bool(leap_month.value) if calendar.value == "lunar" else False
                    existing.leap_policy = leap_policy.value or "normal"
                    existing.notes = notes.value.strip()
                    existing.deleted = False
                    existing.touch()
                    validate_record(existing)
                else:
                    new_record = BirthdayRecord.new(
                        name=name.value,
                        relation=relation.value,
                        calendar=calendar.value,
                        month=m,
                        day=d,
                        birth_year=by,
                        leap_month=bool(leap_month.value) if calendar.value == "lunar" else False,
                        leap_policy=leap_policy.value or "normal",
                        notes=notes.value,
                    )
                    validate_record(new_record)
                    records.append(new_record)
                save_all()
                page.pop_dialog()
                quick.value = ""
                set_status("已保存到本机。")
                render_list()
            except Exception as exc:
                form_error.value = str(exc)
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("编辑生日" if existing else "添加生日"),
            content=ft.Container(
                width=460,
                content=ft.Column(
                    [
                        name,
                        relation,
                        calendar,
                        ft.Row([month, day]),
                        birth_year,
                        leap_month,
                        leap_policy,
                        notes,
                        form_error,
                    ],
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: page.pop_dialog()),
                ft.Button("保存", icon=ft.Icons.SAVE, on_click=do_save),
            ],
        )
        refresh_lunar_fields()
        page.show_dialog(dialog)

    def handle_quick_add(e):
        try:
            preset = parse_quick(quick.value or "")
            open_editor(preset=preset)
            set_status("已识别，确认后保存即可。")
        except Exception as exc:
            set_status(str(exc))

    async def export_backup(e):
        data = backup_bytes()
        name = f"家庭生日备份_{date.today():%Y%m%d}.json"
        try:
            path = await ft.FilePicker().save_file(
                file_name=name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                src_bytes=data,
            )
            set_status(f"备份已导出{('：' + path) if path else ''}")
        except Exception as exc:
            set_status(f"导出失败：{exc}")

    async def share_backup(e):
        data = backup_bytes()
        name = f"家庭生日备份_{date.today():%Y%m%d}.json"
        try:
            await ft.Share().share_files(
                [ft.ShareFile.from_bytes(data, mime_type="application/json", name=name)],
                title="分享家庭生日备份",
                text="这是家庭生日管理器的离线备份文件。",
            )
            set_status("已打开系统分享面板。")
        except Exception as exc:
            set_status(f"分享失败：{exc}")

    async def import_backup(e):
        try:
            files = await ft.FilePicker().pick_files(
                allow_multiple=False,
                with_data=True,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
            )
            if not files:
                return
            if not files[0].bytes:
                raise ValueError("没有读取到文件内容")
            merged = import_backup_bytes(files[0].bytes, records)
            records.clear()
            records.extend(merged)
            save_all()
            set_status("导入完成：已按记录 ID 和更新时间合并，不会简单覆盖另一端新增的数据。")
            render_list()
        except Exception as exc:
            set_status(f"导入失败：{exc}")

    def ics_bytes() -> bytes:
        with records_lock:
            return build_ics(records, years=20).encode("utf-8")

    async def export_ics(e):
        data = ics_bytes()
        name = f"家庭生日_未来20年_{date.today():%Y%m%d}.ics"
        try:
            path = await ft.FilePicker().save_file(
                file_name=name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["ics"],
                src_bytes=data,
            )
            set_status(f"日历文件已导出{('：' + path) if path else ''}。导入手机/电脑本地日历即可离线提醒。")
        except Exception as exc:
            set_status(f"导出失败：{exc}")

    async def share_ics(e):
        data = ics_bytes()
        name = f"家庭生日_未来20年_{date.today():%Y%m%d}.ics"
        try:
            await ft.Share().share_files(
                [ft.ShareFile.from_bytes(data, mime_type="text/calendar", name=name)],
                title="分享家庭生日历",
                text="导入本地日历后可在无网络状态下提醒。",
            )
            set_status("已打开系统分享面板。")
        except Exception as exc:
            set_status(f"分享失败：{exc}")

    def open_lan_sync(e=None):
        nonlocal lan_server

        host_status = ft.Text("尚未启动。", size=13)
        host_info = ft.Text("", selectable=True)
        qr_image = ft.Image(src=b"", width=220, height=220, visible=False)
        address_input = ft.TextField(label="另一台设备的地址", hint_text="例如：192.168.1.23:54321")
        code_input = ft.TextField(label="6 位配对码", hint_text="例如：083521", max_length=6)
        client_status = ft.Text("", size=13)

        def stop_host():
            nonlocal lan_server
            if lan_server is not None:
                lan_server.stop()
                lan_server = None

        def close_dialog(e=None):
            stop_host()
            page.pop_dialog()
            render_list()
            set_status("局域网同步窗口已关闭。")

        def start_host(e):
            nonlocal lan_server
            try:
                stop_host()
                lan_server = LanSyncServer(backup_bytes, merge_lan_backup)
                lan_server.start()
                host_info.value = (
                    f"局域网地址：{lan_server.address}\n"
                    f"配对码：{lan_server.pair_code}\n"
                    f"扫码地址：{lan_server.browser_url}"
                )
                if lan_server.host_ip.startswith("127."):
                    host_status.value = "已启动，但当前只发现本机回环地址；请先连接 Wi-Fi / 局域网。"
                else:
                    host_status.value = "已启动。保持此窗口打开，另一台设备即可连接。"
                try:
                    qr_image.src = qr_png_base64(lan_server.browser_url)
                    qr_image.visible = True
                except Exception as exc:
                    qr_image.visible = False
                    host_status.value += f" 二维码生成失败：{exc}"
                page.update()
            except Exception as exc:
                host_status.value = f"启动失败：{exc}"
                page.update()

        async def connect_and_sync(e):
            try:
                client_status.value = "正在双向同步……"
                page.update()
                raw = await asyncio.to_thread(
                    sync_with_peer,
                    address_input.value or "",
                    code_input.value or "",
                    backup_bytes(),
                )
                with records_lock:
                    merged = import_backup_bytes(raw, records)
                    records.clear()
                    records.extend(merged)
                    save_records(records)
                client_status.value = "同步成功：两端数据已合并，本机已保存最新结果。"
                render_list()
            except Exception as exc:
                client_status.value = f"同步失败：{exc}"
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("局域网双向同步 · v0.2"),
            content=ft.Container(
                width=560,
                content=ft.Column(
                    [
                        ft.Text("方式一：这台设备作为主机", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "两台设备连接同一个 Wi-Fi / 局域网后，点击启动。另一台安装本应用的设备可输入下面的地址和配对码直接双向同步；也可用手机系统相机扫描二维码，在浏览器中下载/上传备份。",
                            size=13,
                        ),
                        ft.Button("启动本机同步服务", icon=ft.Icons.WIFI_TETHERING, on_click=start_host),
                        host_status,
                        host_info,
                        ft.Container(content=qr_image, alignment=ft.Alignment.CENTER),
                        ft.Divider(),
                        ft.Text("方式二：连接另一台设备", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text("输入对方显示的局域网地址与 6 位配对码，点一次即可把两端生日数据合并。", size=13),
                        address_input,
                        code_input,
                        ft.Button("双向同步", icon=ft.Icons.SYNC, on_click=connect_and_sync),
                        client_status,
                        ft.Text("安全限制：客户端只允许连接私有/本地 IP；同步服务仅在当前局域网临时开放，关闭此窗口后立即停止。", size=12),
                    ],
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[ft.TextButton("关闭", on_click=close_dialog)],
        )
        page.show_dialog(dialog)

    page.add(
        ft.SafeArea(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column([
                                ft.Text("家庭生日管理器", size=28, weight=ft.FontWeight.BOLD),
                                ft.Text("公历 + 农历 · 完全离线 · Windows / Android · v0.2 开发版", size=13),
                            ], spacing=2, expand=True),
                            ft.Button("添加生日", icon=ft.Icons.ADD, on_click=lambda e: open_editor()),
                        ]
                    ),
                    ft.Divider(),
                    ft.Row([quick, ft.Button("识别并添加", icon=ft.Icons.AUTO_AWESOME, on_click=handle_quick_add)]),
                    status,
                    ft.Text("最近生日", size=20, weight=ft.FontWeight.BOLD),
                    birthday_list,
                    ft.Divider(),
                    ft.Text("备份、两端迁移与本地日历", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "电脑和手机各自保存本地数据。需要同步时，在一端导出/分享 JSON，另一端“导入并合并”；"
                        "删除操作也会随备份同步。ICS 会生成未来 20 年的公历实际日期，农历生日也无需联网换算。",
                        size=13,
                    ),
                    ft.Row(
                        [
                            ft.Button("局域网双向同步", icon=ft.Icons.WIFI_TETHERING, on_click=open_lan_sync),
                            ft.Button("导出备份", icon=ft.Icons.SAVE_ALT, on_click=export_backup),
                            ft.Button("导入并合并", icon=ft.Icons.MERGE, on_click=import_backup),
                            ft.Button("分享备份", icon=ft.Icons.SHARE, on_click=share_backup),
                        ],
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.Button("导出 20 年 ICS", icon=ft.Icons.CALENDAR_MONTH, on_click=export_ics),
                            ft.Button("分享 ICS", icon=ft.Icons.SHARE, on_click=share_ics),
                        ],
                        wrap=True,
                    ),
                    ft.Text(
                        "说明：农历换算范围为 1900–2099。农历三十遇小月时默认按廿九提醒；公历 2 月 29 日在平年默认按 2 月 28 日提醒。",
                        size=12,
                    ),
                ],
                spacing=12,
            )
        )
    )
    render_list()


if __name__ == "__main__":
    ft.run(main)
