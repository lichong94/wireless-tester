# Windows 版使用说明

## 直接运行

本程序为目录模式（启动免解压、速度快）：解压后保持 **`无线测试工具` 文件夹完整**，进入文件夹双击里面的 **无线测试工具.exe** 即可，无需安装 Python 环境。请勿只单独拷贝 exe（依赖文件在同目录）。打开默认全屏。

## 操作流程

1. 先在顶部填写 **流程单号、测试区域、测试人员**；测试时间由程序自动生成，无需手填。
2. 点击 **开始测试**，软件按任务计划逐项执行：
   - 命令在后台隐藏运行，结果实时回显到内置黑色 CMD 终端区，不弹出真实黑窗口；
   - 左侧任务计划逐项标记：待执行 → 进行中 → 已完成 → 已截图；
   - 每完成一项自动截取终端结果作为证据图，随后清空终端；
   - 点击 **“确定，继续下一项”** 后才进入下一项。
3. 网关在地址获取后自动填入 Ping / 漫游目标框。
4. 四项完成后点击 **生成测试报告**，选择保存位置，生成带截图证据的 Word(.docx) 报告；也可 **导出 TXT 记录**。
5. 全部测试完成后，顶部单号/区域/人员表单自动清空。

## 测试模块

- **地址获取**：IPv4、掩码、网关、DNS、MAC、DHCP。
- **信号强度**：SSID、BSSID、信道、频段、制式、信号百分比、估算 dBm、协商速率、评定。
- **定点 Ping**：默认 100 包，逐包时延，汇总收发/丢失/丢包率/最小/平均/最大时延/抖动。
- **无线漫游**：`ping -t` 持续长 Ping，由现场在弹窗中手动停止；记录 AP 切换事件、过程丢包、最长中断时长。

## 结论判定标准

- 信号：RSSI ≥ -60 dBm 优；-60～-70 良；-70～-80 一般；< -80 差。
- 定点 Ping：丢包率 0% 优；≤1% 可接受；>1% 异常。
- 漫游：零丢包正常；丢包 ≤1 且中断 ≤2 秒可接受；其余异常。

## 从源码重新打包

环境：Python 3.8+，安装依赖：

```powershell
python -m pip install pyinstaller python-docx Pillow
```

在本目录执行（目录模式，启动快；排除未使用的 numpy/psutil/win32com 等大模块）：

```powershell
python -m PyInstaller --noconfirm --clean --windowed --name "无线测试工具" --collect-all docx --collect-all PIL --exclude-module numpy --exclude-module psutil --exclude-module win32com --exclude-module Pythonwin --exclude-module pywin32 wifitester.py
```

产物位于 `dist/无线测试工具/` 目录，整体拷贝该文件夹即可运行。

## 报告生成

报告在后台线程生成，界面弹出带 **真实阶段进度条** 的等待窗（创建文档 → 写入分项 → 结论签字 → 保存），不会界面假死；生成完成后自动关闭等待窗并提示保存结果。

## 源码文件

- `wifitester.py`：单页全屏界面、任务计划调度、CMD 终端回显、自动截图、报告调用。
- `netutils.py`：`ipconfig /all` 与 `netsh wlan show interfaces` 解析、后台隐藏 Ping 调用与统计。
- `report_generator.py`：Word 报告生成（基础信息、分项章节、参数表、截图证据、总体结论、签字栏）。
