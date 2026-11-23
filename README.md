# 无线网络测试工具（Windows 版 + 安卓 App）

面向局域网现场无线测试的双端工具，覆盖地址获取、信号强度、定点 Ping、无线漫游四类测试，并可一键生成带命令运行结果截图证据的 Word 测试报告。网线距离及接口速率按需求为单独测试项，未包含在软件内。

## 功能清单

| 模块 | Windows 版 | 安卓 App | 说明 |
| --- | --- | --- | --- |
| 1. 测试地址获取 | ✅ | ✅ | 仅取无线网卡 IP、掩码、网关、DNS、SSID、BSSID、MAC/DHCP |
| 2. 测试信号强度 | ✅ | ✅ | RSSI(dBm)、频段、信道、制式、协商速率、评定 |
| 3. 定点 Ping 测试 | ✅ | ✅ | 默认 100 包，统计收发、丢包率、最小/平均/最大时延、抖动；截图聚焦结尾统计信息 |
| 4. 无线漫游测试 | ✅ | ✅ | 持续长 Ping，弹窗由用户手动停止；记录 AP 切换、过程丢包、最长中断时长 |
| 5. 测试报告生成 | ✅ Word(.docx) | ✅ Word(.docx) | 含基础信息、分项详情、参数表、（Windows 端含）截图证据、总体结论 |
| 6. 网线距离及接口速率 | ➖ | ➖ | 单独测试，未包含在软件内 |

## 目录结构

```
WirelessTester/
├── windows/                  Windows 电脑版（Python + Tkinter）
│   ├── wifitester.py         图形主程序（单页全屏、终端回显、任务计划、截图、复位）
│   ├── netutils.py           系统采集、无线网卡匹配、Ping 解析与持续 Ping 进程
│   ├── report_generator.py   Word 报告生成器
│   └── README.md
├── android/                  安卓 App（Java 原生工程）
│   └── app/src/main/...      源码、布局、清单、FileProvider 配置
└── README.md
```

## Windows 版运行与打包

- 依赖：Python 3.8+、python-docx、Pillow、PyInstaller。
- 直接运行：`python wifitester.py`。
- 打包为目录模式：

```powershell
python -m PyInstaller --noconfirm --clean --windowed --name "无线测试工具" --collect-all docx --collect-all PIL --exclude-module numpy --exclude-module psutil --exclude-module win32com wifitester.py
```

## 安卓版编译

- 语言：Java；AGP 8.1.4 / Gradle 8.2 / JDK 17；compileSdk 33、minSdk 21、targetSdk 33。
- Android Studio 打开 `android/` 目录同步后 Build APK；或命令行 `gradle assembleDebug`。
- release 签名密钥库不纳入本仓库；如需正式签名，请在本地自行生成密钥库并在 `app/build.gradle` 的 signingConfig 中配置。

## 现场使用要点

- 连接目标 SSID 后再测试；Ping 目标填网关或内网服务器，不要填公网地址。
- 漫游测试时从起始 AP 覆盖边缘向相邻 AP 方向匀速移动。
- 安卓部分机型在未开启位置开关时无法读取 BSSID，测试前请开启位置服务。
