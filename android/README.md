# 安卓 App 编译说明

## 工程信息

- 包名：`com.nzbb.wifitester`
- minSdk：21（Android 5.0+），targetSdk：33
- 语言：Java，构建：AGP 8.1.4 / Gradle 8.2 / JDK 17

## 签名说明（release 正式签名）

签名密钥库不纳入本仓库。如需产出正式签名 release 包，请在工程根目录新建 `keystore.properties`（已被 .gitignore 排除），配置本地密钥库信息：

```properties
storeFile=app/your.jks
storePassword=你的库口令
keyAlias=你的别名
keyPassword=你的密钥口令
```

未配置该文件时，`assembleRelease` 产出的包使用默认 debug 签名。升级覆盖安装时需沿用同一密钥库，否则签名不一致无法覆盖安装。

## 编译生成 APK

### 方式一：Android Studio（推荐）

1. 安装 Android Studio Hedgehog（2023.1）或更高版本。
2. 选择 “Open”，打开本 `android/` 目录（含 settings.gradle 的目录）。
3. 等待 Gradle 同步完成（首次会自动下载 SDK 依赖）。
4. 菜单 `Build → Build Bundle(s) / APK(s) → Build APK(s)`。
5. 产物路径：`app/build/outputs/apk/debug/app-debug.apk`，传到手机安装即可。

### 方式二：命令行（已装 Android SDK 与 Gradle）

```bash
# 在 android/ 目录下
gradle assembleDebug    # 调试包（debug 证书）
gradle assembleRelease  # 正式签名包（需本地配置 keystore.properties）
```

- 调试包：`app/build/outputs/apk/debug/app-debug.apk`
- 正式签名包：`app/build/outputs/apk/release/app-release.apk`

校验签名：

```bash
apksigner verify --print-certs app-release.apk
```

## 权限说明

- `INTERNET`：执行 Ping 测试。
- `ACCESS_WIFI_STATE / CHANGE_WIFI_STATE / ACCESS_NETWORK_STATE`：读取 WiFi 连接与链路信息。
- `ACCESS_FINE_LOCATION`：获取 BSSID 与扫描结果必需，首次启动会申请。

## App 功能

1. **地址获取**：SSID、BSSID、IP、掩码、网关、DNS1/DNS2、MAC（安卓 6.0 后 MAC 随机化）。
2. **信号强度**：RSSI(dBm)、频段、信道、协商速率、制式、信号评定。
3. **定点 Ping**：默认 100 包，统计收发、丢包率、最小/平均/最大时延与结论。
4. **无线漫游**：持续长 Ping，由用户在弹窗中手动停止；记录 AP 切换事件、切换次数、过程丢包、最长中断时长与结论。
5. **测试报告**：一键生成 Word(.docx) 文档，模板与电脑端一致（基础信息、测试目的/过程方法/结果分析、参数表、总体结论、签字栏），可在手机上打开或分享。

## 现场使用要点

- 连接目标 SSID 后再测试；Ping 目标填网关或内网服务器，不要填公网地址。
- 漫游测试时从起始 AP 覆盖边缘向相邻 AP 方向匀速移动，往返各测一次。
- 安卓系统限制：部分机型在未开启位置开关时无法读取 BSSID，测试前请开启位置服务。

## 源码结构

```
app/src/main/
├── AndroidManifest.xml                 权限与 Activity 注册
├── java/com/nzbb/wifitester/
│   └── MainActivity.java               全部采集、Ping、漫游逻辑
└── res/
    ├── layout/activity_main.xml        界面布局
    └── values/                         字符串、主题
```
