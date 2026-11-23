# -*- coding: utf-8 -*-
"""
无线测试工具 - Windows 系统采集模块
功能：
1. 地址获取：解析 ipconfig /all，提取各网卡 IPv4、掩码、网关、DNS、MAC、DHCP
2. 信号强度：解析 netsh wlan show interfaces，提取 SSID、BSSID、信道、信号、协商速率、频段、制式
3. 单点 ping：调用系统 ping.exe，逐包统计时延与丢包
说明：本模块只做采集与解析，不包含界面代码。
"""

import re
import subprocess
import time

# 隐藏控制台窗口标志：避免调用 ipconfig / ping / netsh 时弹出黑色命令行窗口
_CREATE_NO_WINDOW = 0x08000000


def _hidden_startupinfo():
    """生成隐藏窗口的进程启动信息（Windows）。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


# ----------------------------------------------------------------------------
# 通用命令执行
# ----------------------------------------------------------------------------

def _run_command(args):
    """执行系统命令，返回文本输出；后台隐藏窗口运行，兼容中文 GBK 编码，失败返回空字符串。"""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            encoding="gbk",
            errors="ignore",
            timeout=30,
            creationflags=_CREATE_NO_WINDOW,
            startupinfo=_hidden_startupinfo(),
        )
        return proc.stdout or ""
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# 1. 地址获取：解析 ipconfig /all
# ----------------------------------------------------------------------------

def _normalize_key(text):
    """去掉字段名中的点号、空格、冒号、括号，便于中英文宽松匹配。"""
    return re.sub(r"[\s.:：()（）]", "", text).lower()


def run_ipconfig():
    """返回 `ipconfig /all` 原始文本（后台隐藏运行），用于终端回显与证据截图。"""
    return _run_command(["ipconfig", "/all"])


def run_wlan_show():
    """返回 `netsh wlan show interfaces` 原始文本，用于终端回显与证据截图。"""
    return _run_command(["netsh", "wlan", "show", "interfaces"])


def get_adapters_info(raw=None):
    """
    解析 `ipconfig /all`，返回网卡信息列表。
    raw 可传入已获取的原始文本，避免重复执行命令。
    每条记录字段：
        name        网卡名称
        ipv4        IPv4 地址
        mask        子网掩码
        gateway     默认网关
        dns         DNS 服务器（多个用分号分隔）
        mac         物理地址
        dhcp        DHCP 是否启用（是/否/未知）
        ipv6        IPv6 地址（可选）
    """
    output = raw if raw is not None else _run_command(["ipconfig", "/all"])
    adapters = []
    current = None
    prev_key_n = ""  # 记录上一个字段，用于无字段名的续行累积

    # 网卡段：中文“适配器 xxx:”、英文“Ethernet adapter xxx:”均可识别
    adapter_header = re.compile(r"(?:adapter|适配器)\s+(.+?)\s*:\s*$", re.I)

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        header = adapter_header.search(line.strip())
        if header:
            # 保存上一块网卡
            if current:
                adapters.append(current)
            current = {
                "name": header.group(1).strip(),
                "ipv4": "",
                "mask": "",
                "gateway": "",
                "ipv4_gateway": "",
                "dns": "",
                "mac": "",
                "dhcp": "未知",
                "ipv6": "",
            }
            prev_key_n = ""
            continue

        if current is None:
            continue

        # 无冒号的续行：追加到上一个多值字段（网关 / DNS）
        if ":" not in line:
            cont = line.strip()
            if prev_key_n in ("defaultgateway", "默认网关"):
                current["gateway"] = (current["gateway"] + ";" + cont).strip(";")
                v4 = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", cont)
                if v4:
                    current["ipv4_gateway"] = v4.group(1)
            elif prev_key_n in ("dnsservers", "dns服务器"):
                current["dns"] = (current["dns"] + ";" + cont).strip(";")
            continue

        key, _, value = line.partition(":")
        key_n = _normalize_key(key)
        value = value.strip()
        prev_key_n = key_n

        # IPv4 地址（去掉括号备注，如 192.168.1.100(首选)）
        if key_n in ("ipv4地址", "ipv4address"):
            current["ipv4"] = re.sub(r"\(.*?\)", "", value).strip()
        elif key_n in ("子网掩码", "subnetmask"):
            current["mask"] = value
        elif key_n in ("默认网关", "defaultgateway"):
            current["gateway"] = (current["gateway"] + ";" + value).strip(";") if value else current["gateway"]
            v4 = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", value)
            if v4:
                current["ipv4_gateway"] = v4.group(1)
        elif key_n in ("dns服务器", "dnsservers"):
            # 同一网卡 DNS 可能分多行，累积拼接
            current["dns"] = (current["dns"] + ";" + value).strip(";") if value else current["dns"]
        elif key_n in ("物理地址", "physicaladdress"):
            current["mac"] = value
        elif key_n in ("dhcp已启用", "dhcpenabled"):
            current["dhcp"] = "是" if value.lower() in ("是", "yes", "启用", "enabled") else "否"
        elif key_n in ("ipv6地址", "ipv6address", "链接本地ipv6地址", "link-localipv6address", "link-local-ipv6address"):
            if not current["ipv6"]:
                current["ipv6"] = re.sub(r"\(.*?\)", "", value).strip()

    if current:
        adapters.append(current)

    # 只保留存在有效 IPv4 的网卡
    return [a for a in adapters if a["ipv4"]]


def pick_wlan_adapter(adapters, wlan_ifname=""):
    """
    从网卡列表中挑出无线网卡条目。
    优先用 netsh 读到的无线接口名精确匹配；匹配不到再按名称前缀兜底；
    都识别不出时返回第一条，避免界面无数据。
    """
    if not adapters:
        return None
    if wlan_ifname:
        wn = wlan_ifname.strip().lower()
        for a in adapters:
            if a["name"].strip().lower() == wn:
                return a
        for a in adapters:
            if wn and wn in a["name"].strip().lower():
                return a
    for a in adapters:
        n = a["name"].lower()
        if n.startswith(("wlan", "wireless", "无线", "wi-fi", "wifi")):
            return a
    return adapters[0]


# ----------------------------------------------------------------------------
# 2. 信号强度：解析 netsh wlan show interfaces
# ----------------------------------------------------------------------------

def _parse_signal_percent(text):
    """从“信号 : 80%”一类文本中提取百分比数值。"""
    m = re.search(r"(\d{1,3})\s*%", text)
    return int(m.group(1)) if m else None


def percent_to_dbm(percent):
    """
    信号百分比换算为估算 dBm。
    经验公式：dBm ≈ -100 + 百分比 / 2（0% 约 -100dBm，100% 约 -50dBm）。
    netsh 不直接给出 dBm，此结果为估算值，界面中需注明。
    """
    if percent is None:
        return None
    return round(-100 + percent / 2.0, 1)


def get_wlan_interface(raw=None):
    """
    解析 `netsh wlan show interfaces`，返回当前无线网卡状态字典。
    raw 可传入已获取的原始文本，避免重复执行命令。
    字段：
        ssid        无线网络名称
        bssid       接入点 MAC
        channel     信道
        signal_per  信号百分比
        signal_dbm 估算 dBm
        rx_rate     接收协商速率 Mbps
        tx_rate     发送协商速率 Mbps
        band        频段（2.4GHz / 5GHz / 6GHz，识别不到为空）
        standard    无线制式（802.11a/b/g/n/ac/ax/be）
        state       连接状态
    """
    output = raw if raw is not None else _run_command(["netsh", "wlan", "show", "interfaces"])
    info = {
        "ifname": "",
        "ssid": "",
        "bssid": "",
        "channel": "",
        "signal_per": None,
        "signal_dbm": None,
        "rx_rate": "",
        "tx_rate": "",
        "band": "",
        "standard": "",
        "state": "",
    }

    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        key_n = _normalize_key(key)
        value = value.strip()

        if key_n in ("名称", "name"):
            info["ifname"] = value
        elif key_n in ("名称ssid", "ssid"):
            info["ssid"] = value
        elif key_n in ("bssid",):
            info["bssid"] = value
        elif key_n in ("信道", "channel"):
            info["channel"] = value
        elif key_n in ("信号", "signal"):
            info["signal_per"] = _parse_signal_percent(value)
            info["signal_dbm"] = percent_to_dbm(info["signal_per"])
        elif key_n in ("接收速率mbps", "接收速率", "receiverate", "receiveratembps", "receivekey速率"):
            info["rx_rate"] = value
        elif key_n in ("传输速率mbps", "传输速率", "txrate", "transmitrate", "transmitratembps"):
            info["tx_rate"] = value
        elif key_n in ("频段", "band"):
            info["band"] = value
        elif key_n in ("无线电类型", "无线类型", "standard", "radiotype"):
            info["standard"] = value
        elif key_n in ("状态", "state"):
            info["state"] = value

    # 频段兜底：根据信道号推断
    if not info["band"] and info["channel"].isdigit():
        ch = int(info["channel"])
        if ch <= 14:
            info["band"] = "2.4 GHz"
        else:
            info["band"] = "5 GHz"

    return info


def judge_signal(dbm):
    """按 RSSI 评定信号等级：优 / 良 / 一般 / 差 / 未知。"""
    if dbm is None:
        return "未知"
    if dbm >= -60:
        return "优"
    if dbm >= -70:
        return "良"
    if dbm >= -80:
        return "一般"
    return "差"


# ----------------------------------------------------------------------------
# 3. ping 测试
# ----------------------------------------------------------------------------

# 匹配单包时延，兼容中英文：时间=23ms / time=23ms / 时间<2ms
_LATENCY_RE = re.compile(r"(?:时间|time)\s*[=<]?\s*(\d+(?:\.\d+)?)\s*ms", re.I)
_TIMEOUT_KEYS = ("请求超时", "request timed out", "传输失败", "destination host unreachable")


def ping_once(target, timeout_ms=1000):
    """
    发送单个 ICMP 回显请求。
    返回字典：ok(布尔)、latency_ms(浮点或 None)、raw(原始输出)、timestamp(时间戳)
    """
    timestamp = time.strftime("%H:%M:%S")
    mono = time.time()
    raw = _run_command(["ping", "-n", "1", "-w", str(timeout_ms), target])
    latency = None
    ok = False

    m = _LATENCY_RE.search(raw)
    if m:
        latency = float(m.group(1))
        ok = True
    elif any(k in raw.lower() for k in [x.lower() for x in _TIMEOUT_KEYS]):
        ok = False
    else:
        # 无回显且无超时关键字，判定为失败
        ok = False

    return {"ok": ok, "latency_ms": latency, "raw": raw.strip(), "timestamp": timestamp, "mono": mono}


def _is_packet_line(line):
    """判断一行是否为有效 Ping 回复/超时行（跳过标题、空行、汇总统计行）。"""
    if _LATENCY_RE.search(line):
        return True
    low = line.lower()
    return any(k in low for k in [x.lower() for x in _TIMEOUT_KEYS])


def ping_batch(target, count=100, timeout_ms=1000, on_packet=None):
    """
    连续 ping 指定次数（默认 100）。
    采用单次 `ping -n count` 进程流式读取，避免逐包反复创建进程导致的卡顿；
    逐包回调 on_packet(序号, 结果字典)。
    返回汇总字典：
        target、count、sent、received、lost、loss_rate、
        min_ms、avg_ms、max_ms、jitter_ms、latencies(时延列表)、packets(逐包记录)
    """
    packets = []
    latencies = []

    proc = subprocess.Popen(
        ["ping", "-n", str(count), "-w", str(timeout_ms), target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="gbk",
        errors="ignore",
        bufsize=1,
        creationflags=_CREATE_NO_WINDOW,
        startupinfo=_hidden_startupinfo(),
    )

    seq = 0
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or not _is_packet_line(line):
                continue
            result = parse_ping_line(line)
            seq += 1
            result["seq"] = seq
            packets.append(result)
            if result["ok"] and result["latency_ms"] is not None:
                latencies.append(result["latency_ms"])
            if on_packet:
                on_packet(seq, result)
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    sent = count
    received = len(latencies)
    lost = sent - received
    loss_rate = round(lost / sent * 100, 2) if sent else 0.0

    if latencies:
        min_ms = round(min(latencies), 2)
        max_ms = round(max(latencies), 2)
        avg_ms = round(sum(latencies) / len(latencies), 2)
        jitter_ms = round(max_ms - min_ms, 2)
    else:
        min_ms = avg_ms = max_ms = jitter_ms = None

    return {
        "target": target,
        "count": count,
        "sent": sent,
        "received": received,
        "lost": lost,
        "loss_rate": loss_rate,
        "min_ms": min_ms,
        "avg_ms": avg_ms,
        "max_ms": max_ms,
        "jitter_ms": jitter_ms,
        "latencies": latencies,
        "packets": packets,
    }


def judge_ping(loss_rate, avg_ms):
    """
    定点 ping 结论：优 / 可接受 / 异常。
    优：丢包率 0%；可接受：丢包率 ≤1%；其余异常。
    """
    if loss_rate is None:
        return "未测"
    if loss_rate == 0:
        return "优"
    if loss_rate <= 1:
        return "可接受"
    return "异常"


# ----------------------------------------------------------------------------
# 持续 ping（ping -t，用于无线漫游，由用户手动停止）
# ----------------------------------------------------------------------------

def start_ping_tail(target):
    """
    启动 `ping -t target` 后台持续进程（隐藏窗口），返回 Popen 对象。
    调用方通过 proc.stdout 逐行读取输出；停止时调用 proc.terminate()。
    """
    return subprocess.Popen(
        ["ping", "-t", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="gbk",
        errors="ignore",
        bufsize=1,
        creationflags=_CREATE_NO_WINDOW,
        startupinfo=_hidden_startupinfo(),
    )


def parse_ping_line(line):
    """解析单行 ping 输出，返回与 ping_once 一致结构的结果字典。"""
    latency = None
    ok = False
    m = _LATENCY_RE.search(line)
    if m:
        latency = float(m.group(1))
        ok = True
    elif any(k in line.lower() for k in [x.lower() for x in _TIMEOUT_KEYS]):
        ok = False
    return {
        "ok": ok,
        "latency_ms": latency,
        "raw": line.strip(),
        "timestamp": time.strftime("%H:%M:%S"),
        "mono": time.time(),
    }


if __name__ == "__main__":
    # 自检：打印当前网卡与无线状态
    print("=== 网卡地址 ===")
    for ad in get_adapters_info():
        print(ad)
    print("=== 无线信号 ===")
    print(get_wlan_interface())
