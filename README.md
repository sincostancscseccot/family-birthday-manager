# 家庭生日管理器

一个完全本地运行的 Windows / Android 家庭生日工具，同时支持公历和农历。

## 设计目标

- 数据只保存在设备本地，不要求登录、服务器或互联网。
- Windows 与 Android 使用同一套 Python/Flet 代码。
- 支持公历、农历、闰月生日。
- 首页可快速输入：`奶奶 农历腊月二十`、`妈妈 公历5月12日`。
- 自动显示下一个生日对应的实际公历日期以及剩余天数。
- JSON 备份采用“按 ID + 更新时间合并”，适合电脑/手机离线互传。
- 删除使用 tombstone（删除标记），避免另一端旧备份把已删除的人重新带回来。
- 可导出未来 20 年 `.ics`，导入手机/电脑的本地日历后，由系统日历离线提醒。

## 本地数据

应用内部使用 `family_birthdays.json`。Flet 打包后，它位于系统为应用分配的持久数据目录：

- Windows：应用数据目录（AppData）
- Android：应用私有数据目录

正常升级应用不会清空它；卸载应用前建议先导出 JSON 备份。

## 开发运行

建议 Python 3.13。

```powershell
cd family_birthday_manager
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
flet run main.py
```

## Windows 打包

### 方案 A：Flet 原生 Windows 构建

```powershell
flet build windows . --python-version 3.13
```

该路线需要 Visual Studio 的 **Desktop development with C++** 工作负载。

### 方案 B：PyInstaller / flet pack

如果只想快速得到桌面可执行程序，可以使用 Flet 提供的 PyInstaller 路线：

```powershell
flet pack main.py --name FamilyBirthday
```

## Android APK 打包

Windows 可以直接构建 Android APK：

```powershell
flet build apk . --python-version 3.13
```

第一次构建可能需要下载 Flutter / Android SDK / 构建依赖，因此**构建阶段可能需要网络**；生成的 APK 本身不需要联网运行。

## 两端离线同步

推荐流程：

1. 手机添加/修改生日。
2. 点“分享备份”或“导出备份”，得到 JSON。
3. 通过 USB、蓝牙、局域网分享、数据线等任意离线方式传到电脑。
4. 电脑点“导入并合并”。
5. 反向操作一次，可让两边拥有相同数据。

合并不是简单覆盖：不同设备新增的记录会同时保留；同一条记录以 `updated_at` 较新的版本为准。

## 日历提醒

“导出 20 年 ICS”会把每一年生日的实际公历日期写入标准日历文件。

默认每个事件包含：

- 提前 7 天提醒
- 提前 1 天提醒
- 当天提醒

不同系统日历对全天事件提醒时间的解释可能略有差异。

## 特殊日期规则

- 农历生日支持 1900–2099。
- 闰月生日：可设置“没有对应闰月时按普通同月同日过”或“该年不过”。
- 农历三十遇到当年该月只有 29 天时，默认按廿九提醒。
- 公历 2 月 29 日遇平年时，默认按 2 月 28 日提醒。

这些策略后续可以继续做成每个人独立可配置。
