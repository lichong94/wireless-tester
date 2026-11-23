# -*- coding: utf-8 -*-
"""
无线测试工具 - Windows 图形主程序（单页全屏版）
功能模块：
1. 测试地址获取（仅取无线网卡 IP / 掩码 / 网关 / DNS / MAC / DHCP）
2. 测试信号强度（SSID / BSSID / 信道 / RSSI / 频段 / 制式 / 协商速率）
3. 定点 Ping 包测试（默认 100 包，统计丢包与时延，截图聚焦结尾统计信息）
4. 无线漫游测试（ping -t 持续 ping，由用户在弹窗中手动停止）
说明：
- 所有命令在后台隐藏运行，结果实时回显到内置 CMD 终端区，不弹出真实黑窗口。
- 每完成一项自动截图作为证据；经居中弹窗确认后再进入下一项。
- 开始测试前需填写流程单号、测试区域、测试人员；测试时间取点击“开始测试”的时刻。
- 全部测完后弹窗询问生成 Word 报告，保存完成后清空界面恢复初始状态。
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

import netutils
# report_generator 依赖 docx 较重，延迟到真正生成报告时再导入，加快首屏启动

# 默认定点包数与任务顺序
DEFAULT_COUNT = 100
TASK_KEYS = ["address", "signal", "ping", "roaming"]
TASK_TITLES = {
    "address": "1. 地址获取",
    "signal": "2. 信号强度",
    "ping": "3. 定点 Ping 测试",
    "roaming": "4. 无线漫游测试",
}


def app_base_dir():
    """取程序所在目录（兼容 PyInstaller 打包后的 exe 目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class WifiTesterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("无线网络测试工具 (Windows 版)")
        # 默认全屏最大化
        self.state("zoomed")
        self.minsize(1100, 700)

        # 线程消息队列：工作线程 -> 界面主线程
        self.msg_queue = queue.Queue()

        # 各模块最新结果
        self.result_addr = []
        self.result_signal = {}
        self.result_ping = {}
        self.result_roam = {}
        self.wlan_adapter = None
        self.raw_addr = ""
        self.raw_signal = ""

        # 截图与报告目录
        self.run_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report_dir = os.path.join(app_base_dir(), "reports", self.run_time)
        os.makedirs(self.report_dir, exist_ok=True)
        self.screenshots = {}

        # 任务状态：待执行 / 进行中 / 已完成 / 已截图
        self.task_status = {k: "待执行" for k in TASK_KEYS}
        self.sequence_mode = False      # 是否为顺序引导模式
        self.current_index = -1
        self.ping_stop = False
        self.roam_stop = False

        # 漫游持续 ping 进程与停止弹窗
        self.roam_proc = None
        self.roam_dialog = None

        # 报告生成加载窗（后台线程生成，前端显示真实阶段进度）
        self.report_dlg = None
        self.report_pb = None
        self.report_label = None

        # 测试时间：默认占位，点击“开始测试”时刷新为真实时刻
        self.test_time = ""

        self._build_ui()
        self._refresh_test_time_label()
        self.after(100, self._poll_queue)

    # ==================================================================
    # 界面构建
    # ==================================================================
    def _build_ui(self):
        self._build_topbar()

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        # 左侧：任务计划
        left = ttk.Frame(body, width=280)
        body.add(left, weight=0)
        ttk.Label(left, text="任务计划", font=("黑体", 13, "bold")).pack(anchor=tk.W, pady=(0, 6))
        cols = ("task", "status")
        self.task_tree = ttk.Treeview(left, columns=cols, show="headings", height=6)
        self.task_tree.heading("task", text="测试任务")
        self.task_tree.heading("status", text="状态")
        self.task_tree.column("task", width=170, anchor=tk.W)
        self.task_tree.column("status", width=80, anchor=tk.CENTER)
        for k in TASK_KEYS:
            self.task_tree.insert("", tk.END, iid=k, values=(TASK_TITLES[k], "待执行"))
        self.task_tree.pack(fill=tk.BOTH, expand=True)

        # 右侧：结果摘要 + CMD 终端
        right = ttk.Frame(body)
        body.add(right, weight=1)

        # 结果摘要（四栏紧凑表格）
        summary_wrap = ttk.LabelFrame(right, text="测试结果摘要")
        summary_wrap.pack(fill=tk.X, pady=(0, 6))
        self.summary_vars = {}
        summary_fields = [
            ("address", "地址获取", "—"),
            ("signal", "信号强度", "—"),
            ("ping", "定点 Ping", "—"),
            ("roaming", "无线漫游", "—"),
        ]
        for i, (key, label, default) in enumerate(summary_fields):
            ttk.Label(summary_wrap, text=label + "：").grid(row=0, column=i * 2, sticky=tk.W, padx=6, pady=6)
            var = tk.StringVar(value=default)
            self.summary_vars[key] = var
            ttk.Label(summary_wrap, textvariable=var, width=22, foreground="#1a5fb4").grid(
                row=0, column=i * 2 + 1, sticky=tk.W, padx=6, pady=6)

        # CMD 终端区（黑底等宽字体，模拟命令行窗口）
        term_wrap = ttk.LabelFrame(right, text="CMD 终端（后台运行，实时回显）")
        term_wrap.pack(fill=tk.BOTH, expand=True)
        self.term = scrolledtext.ScrolledText(
            term_wrap, height=16, bg="#0C0C0C", fg="#D4F7D4",
            insertbackground="#D4F7D4", font=("Consolas", 11), state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.term.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # 终端文字颜色标签
        for name, color in [("green", "#D4F7D4"), ("blue", "blue"),
                            ("red", "red"), ("yellow", "yellow")]:
            self.term.tag_configure(name, foreground=color)

        # 底部操作栏：继续按钮居中放置（不放在右下角）
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.status_var = tk.StringVar(value="请填写上方信息后，点击“开始测试”。")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#555").pack(side=tk.LEFT)
        self.btn_next = ttk.Button(bottom, text="确定，继续下一项", command=self.confirm_next,
                                   state=tk.DISABLED)
        self.btn_next.pack(side=tk.BOTTOM, anchor=tk.CENTER, pady=(6, 0))

    def _build_topbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill=tk.X)

        ttk.Label(bar, text="流程单号：").pack(side=tk.LEFT)
        self.var_order = tk.StringVar()
        ttk.Entry(bar, textvariable=self.var_order, width=16).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar, text="测试区域：").pack(side=tk.LEFT)
        self.var_area = tk.StringVar()
        ttk.Entry(bar, textvariable=self.var_area, width=20).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar, text="测试人员：").pack(side=tk.LEFT)
        self.var_person = tk.StringVar()
        ttk.Entry(bar, textvariable=self.var_person, width=12).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar, text="测试时间：").pack(side=tk.LEFT)
        self.time_label = ttk.Label(bar, text="—", foreground="#333")
        self.time_label.pack(side=tk.LEFT, padx=(0, 16))

        self.btn_start = ttk.Button(bar, text="开始测试", command=self.start_sequence)
        self.btn_start.pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="生成测试报告", command=self.generate_report).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="导出 TXT 记录", command=self.export_txt).pack(side=tk.RIGHT, padx=4)

    def _refresh_test_time_label(self):
        self.time_label.config(text=self.test_time or "—")

    # ==================================================================
    # 终端回显
    # ==================================================================
    def log(self, text, tag="green"):
        """向 CMD 终端追加一行（主线程调用），tag 为颜色标签名。"""
        self.term.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self.term.insert(tk.END, f"[{ts}] {text}\n", tag)
        self.term.see(tk.END)
        self.term.config(state=tk.DISABLED)

    def append_lines(self, lines, tag=None):
        """批量追加多行文本，一次性切换可编辑状态，避免逐行反复刷新造成卡顿。"""
        lines = [ln for ln in lines if ln is not None]
        if not lines:
            return
        self.term.config(state=tk.NORMAL)
        for ln in lines:
            self.term.insert(tk.END, ln + "\n", tag)
        self.term.see(tk.END)
        self.term.config(state=tk.DISABLED)

    def clear_terminal(self):
        self.term.config(state=tk.NORMAL)
        self.term.delete("1.0", tk.END)
        self.term.config(state=tk.DISABLED)

    # ==================================================================
    # 任务状态
    # ==================================================================
    def set_task_status(self, key, status):
        self.task_status[key] = status
        self.task_tree.item(key, values=(TASK_TITLES[key], status))

    # ==================================================================
    # 开始测试（顺序引导）
    # ==================================================================
    def start_sequence(self):
        # 开始前校验必填信息
        if not self.var_order.get().strip():
            messagebox.showwarning("提示", "请先填写流程单号。")
            return
        if not self.var_area.get().strip():
            messagebox.showwarning("提示", "请先填写测试区域。")
            return
        if not self.var_person.get().strip():
            messagebox.showwarning("提示", "请先填写测试人员。")
            return

        # 测试时间取点击“开始测试”的时刻
        self.test_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        self._refresh_test_time_label()

        self.sequence_mode = True
        self.current_index = 0
        self.btn_start.config(state=tk.DISABLED)
        self._run_current_task()

    def _run_current_task(self):
        if self.current_index >= len(TASK_KEYS):
            self._sequence_finished()
            return
        key = TASK_KEYS[self.current_index]
        self.set_task_status(key, "进行中")
        self.clear_terminal()
        if key == "address":
            self.run_address()
        elif key == "signal":
            self.run_signal()
        elif key == "ping":
            self.run_ping()
        elif key == "roaming":
            self.run_roam()

    def confirm_next(self):
        """用户确认当前项完成，进入下一项（居中备用按钮触发）。"""
        self.btn_next.config(state=tk.DISABLED)
        self.current_index += 1
        self._run_current_task()

    def _ask_next(self):
        """当前项完成后弹居中确认框，询问是否进行下一项。"""
        key = TASK_KEYS[self.current_index]
        ans = messagebox.askyesno(
            "测试完成",
            f"{TASK_TITLES[key]} 已完成，证据截图已保存。\n\n是否进行下一项？",
            icon=messagebox.QUESTION,
        )
        if ans:
            self.confirm_next()
        else:
            # 暂停在当前项，启用居中的继续按钮，等待用户稍后继续
            self.btn_next.config(state=tk.NORMAL)
            self.status_var.set(f"{TASK_TITLES[key]} 已暂停，核对结果后点击“继续下一项”。")

    def _sequence_finished(self):
        """四项全部完成：弹窗询问是否生成 Word 报告。"""
        self.sequence_mode = False
        self.log("全部测试任务已完成。", "yellow")
        ans = messagebox.askyesno(
            "测试完成",
            "四项测试已全部完成并截图。\n\n是否生成无线测试报告（Word 文档）？",
            icon=messagebox.QUESTION,
        )
        if ans:
            self.generate_report(auto=True)
        else:
            # 暂不生成：直接清空界面，恢复初始状态
            self.reset_all()

    # ==================================================================
    # 模块一：地址获取（仅取无线网卡）
    # ==================================================================
    def run_address(self):
        self.log("执行命令：ipconfig /all")

        def worker():
            raw_addr = netutils.run_ipconfig()
            raw_sig = netutils.run_wlan_show()
            self.msg_queue.put(("addr_both", (raw_addr, raw_sig)))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_addr(self, raw_addr, raw_sig):
        self.raw_addr = raw_addr
        self.raw_signal = raw_sig
        self.log("---- ipconfig /all 输出 ----", "blue")
        self.append_lines(raw_addr.splitlines())

        self.result_addr = netutils.get_adapters_info(raw_addr)
        # 用 netsh 读到的无线接口名，在 ipconfig 结果中精确匹配无线网卡
        wlan_if = netutils.get_wlan_interface(raw_sig)
        self.wlan_adapter = netutils.pick_wlan_adapter(self.result_addr, wlan_if.get("ifname", ""))

        if self.wlan_adapter:
            ad = self.wlan_adapter
            if ad["ipv4_gateway"]:
                self._gateway = ad["ipv4_gateway"]
                self.log(f"无线网卡：{ad['name']}  默认网关：{ad['ipv4_gateway']}（已自动填入 Ping / 漫游目标）", "yellow")
            self.summary_vars["address"].set(
                f"{ad['ipv4']} / 网关 {ad['ipv4_gateway'] or ad['gateway'] or '无'}")
        elif self.result_addr:
            first = self.result_addr[0]
            self.summary_vars["address"].set(
                f"{first['ipv4']} / 网关 {first['ipv4_gateway'] or first['gateway'] or '无'}")
        self.set_task_status("address", "已完成")
        self._after_task("address")

    # ==================================================================
    # 模块二：信号强度
    # ==================================================================
    def run_signal(self):
        self.log("执行命令：netsh wlan show interfaces")

        def worker():
            raw = netutils.run_wlan_show()
            self.msg_queue.put(("signal_raw", raw))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_signal(self, raw):
        self.raw_signal = raw
        self.log("---- netsh 无线接口输出 ----", "blue")
        self.append_lines(raw.splitlines())

        info = netutils.get_wlan_interface(raw)
        info["judge"] = netutils.judge_signal(info["signal_dbm"])
        self.result_signal = info
        self.summary_vars["signal"].set(
            f"{info['signal_dbm']} dBm / {info['band']} / {info['standard']} / {info['judge']}")
        self.set_task_status("signal", "已完成")
        self._after_task("signal")

    # ==================================================================
    # 模块三：定点 Ping 100 包（终端聚焦结尾统计信息）
    # ==================================================================
    def _default_target(self):
        return getattr(self, "_gateway", "")

    def run_ping(self):
        target = self._default_target()
        if not target:
            target = "192.168.1.1"
        self.ping_stop = False
        self.log(f"执行命令：ping -n {DEFAULT_COUNT} {target}")

        def worker():
            def on_packet(seq, result):
                if self.ping_stop:
                    return
                self.msg_queue.put(("ping_packet", result))

            summary = netutils.ping_batch(target, DEFAULT_COUNT, on_packet=on_packet)
            summary["judge"] = netutils.judge_ping(summary["loss_rate"], summary["avg_ms"])
            self.msg_queue.put(("ping_summary", summary))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_ping_packet(self, p):
        self.status_var.set(f"定点 Ping 进行中… 第 {p['seq']}/{DEFAULT_COUNT} 包")
        if p["ok"]:
            self.log(f"第{p['seq']}包  时延 {p['latency_ms']} ms　{p['raw']}")
        else:
            self.log(f"第{p['seq']}包  请求超时 / 丢失　{p['raw']}", "red")

    def _handle_ping_summary(self, s):
        self.result_ping = s
        # 终端只保留结尾统计汇总，作为截图主体
        self.log("---- Ping 统计汇总 ----", "blue")
        self.log(f"发送 {s['sent']}  接收 {s['received']}  丢失 {s['lost']}  丢包率 {s['loss_rate']}%")
        self.log(f"时延 最小 {s['min_ms']} / 平均 {s['avg_ms']} / 最大 {s['max_ms']} ms  抖动 {s['jitter_ms']} ms")
        self.summary_vars["ping"].set(
            f"丢包 {s['lost']}（{s['loss_rate']}%） 平均 {s['avg_ms']} ms  结论 {s['judge']}")
        self.set_task_status("ping", "已完成")
        self._after_task("ping")

    # ==================================================================
    # 模块四：无线漫游测试（ping -t 持续 ping，弹窗手动停止）
    # ==================================================================
    def run_roam(self):
        target = self._default_target() or "192.168.1.1"
        self.roam_stop = False
        self.log(f"执行命令：ping -t {target}（持续 Ping，手动停止）")

        def worker():
            events = []
            packets = []
            prev_bssid = None
            switch_count = 0

            start_if = netutils.get_wlan_interface()
            prev_bssid = start_if["bssid"]
            first_event = {
                "time": time.strftime("%H:%M:%S"),
                "ssid": start_if["ssid"], "bssid": start_if["bssid"],
                "dbm": start_if["signal_dbm"], "note": "起始关联",
            }
            events.append(first_event)
            self.msg_queue.put(("roam_event", first_event))

            # 启动后台持续 ping 进程
            self.roam_proc = netutils.start_ping_tail(target)
            last_check = time.time()

            try:
                while True:
                    line = self.roam_proc.stdout.readline()
                    if not line:
                        break
                    if self.roam_stop:
                        break
                    result = netutils.parse_ping_line(line)
                    result["seq"] = len(packets) + 1
                    packets.append(result)
                    self.msg_queue.put(("roam_packet", result))

                    # 每 2 秒监测一次 AP 切换
                    if time.time() - last_check >= 2:
                        last_check = time.time()
                        cur = netutils.get_wlan_interface()
                        if cur["bssid"] and prev_bssid and cur["bssid"] != prev_bssid:
                            switch_count += 1
                            ev = {
                                "time": time.strftime("%H:%M:%S"),
                                "ssid": cur["ssid"], "bssid": cur["bssid"],
                                "dbm": cur["signal_dbm"], "note": "漫游切换",
                            }
                            events.append(ev)
                            self.msg_queue.put(("roam_event", ev))
                            prev_bssid = cur["bssid"]
            finally:
                try:
                    if self.roam_proc.poll() is None:
                        self.roam_proc.terminate()
                except Exception:
                    pass

            lost = sum(1 for p in packets if not p["ok"])
            loss_rate = round(lost / len(packets) * 100, 2) if packets else 0.0
            latencies = [p["latency_ms"] for p in packets if p["ok"] and p["latency_ms"] is not None]

            max_gap = 0.0
            gap_start = None
            for p in packets:
                if not p["ok"]:
                    if gap_start is None:
                        gap_start = p["mono"]
                    else:
                        max_gap = max(max_gap, p["mono"] - gap_start)
                else:
                    gap_start = None

            end_if = netutils.get_wlan_interface()
            summary = {
                "target": target,
                "start_ap": f'{start_if["ssid"]} ({start_if["bssid"]})',
                "end_ap": f'{end_if["ssid"]} ({end_if["bssid"]})',
                "switch_count": switch_count,
                "sent": len(packets),
                "received": len(latencies),
                "lost": lost,
                "loss_rate": loss_rate,
                "min_ms": round(min(latencies), 2) if latencies else None,
                "avg_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                "max_ms": round(max(latencies), 2) if latencies else None,
                "max_gap": round(max_gap, 2),
                "packets": packets,
                "events": events,
            }
            if lost == 0:
                summary["judge"] = "正常"
            elif lost <= 1 and max_gap <= 2:
                summary["judge"] = "可接受"
            else:
                summary["judge"] = "异常"
            self.msg_queue.put(("roam_summary", summary))

        threading.Thread(target=worker, daemon=True).start()
        # 弹出“停止 Ping”置顶窗口
        self.after(100, self._open_roam_dialog)

    def _open_roam_dialog(self):
        """漫游持续 ping 的控制弹窗：置顶居中，由用户决定停止。"""
        if self.roam_dialog is not None:
            return
        dlg = tk.Toplevel(self)
        dlg.title("无线漫游测试进行中")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        w, h = 420, 200
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        ttk.Label(dlg, text="正在持续 Ping（ping -t）", font=("黑体", 14, "bold")).pack(pady=(24, 8))
        ttk.Label(dlg, text="请沿漫游路径匀速移动，观察信号与 AP 切换；\n测试完成后点击下方按钮停止 Ping。",
                  justify=tk.CENTER).pack(pady=(0, 18))
        ttk.Button(dlg, text="停止 Ping", command=self._stop_roam,
                   style="Accent.TButton").pack(pady=6, ipadx=30, ipady=8)
        dlg.protocol("WM_DELETE_WINDOW", self._stop_roam)
        self.roam_dialog = dlg

    def _stop_roam(self):
        """用户点击停止：终止持续 ping 进程并关闭弹窗。"""
        self.roam_stop = True
        if self.roam_dialog is not None:
            try:
                self.roam_dialog.destroy()
            except Exception:
                pass
            self.roam_dialog = None
        if self.roam_proc is not None:
            try:
                if self.roam_proc.poll() is None:
                    self.roam_proc.terminate()
            except Exception:
                pass

    def _handle_roam_packet(self, p):
        # 逐包回显 CMD 原始记录；超时/丢失在终端标红
        if p["ok"]:
            self.status_var.set(f"漫游 Ping 进行中… 第 {p['seq']} 包，时延 {p['latency_ms']} ms")
            self.log(f"第{p['seq']}包  时延 {p['latency_ms']} ms　{p['raw']}")
        else:
            self.log(f"第{p['seq']}包  请求超时 / 丢失　{p['raw']}", "red")

    def _handle_roam_event(self, ev):
        self.log(f"[事件] {ev['time']} {ev['ssid']} / {ev['bssid']} / {ev['dbm']} dBm / {ev['note']}", "yellow")

    def _handle_roam_summary(self, s):
        self.result_roam = s
        self.log("---- 漫游汇总 ----", "blue")
        self.log(f"起始 AP：{s['start_ap']}")
        self.log(f"结束 AP：{s['end_ap']}")
        self.log(f"发送 {s['sent']}  接收 {s['received']}  过程丢包 {s['lost']}（{s['loss_rate']}%）")
        self.log(f"切换次数 {s['switch_count']}  最长中断 {s['max_gap']}  秒")
        self.summary_vars["roaming"].set(
            f"切换 {s['switch_count']} 次 丢包 {s['lost']}  结论 {s['judge']}")
        self.set_task_status("roaming", "已完成")
        self._after_task("roaming")

    # ==================================================================
    # 单项完成：截图 -> 标记已截图 -> 等待用户确认
    # ==================================================================
    def _after_task(self, key):
        """命令执行完成后自动截图，标记任务已截图，等待用户确认进入下一项。"""
        self.take_screenshot(key)
        self.set_task_status(key, "已截图")
        self.log(f"任务完成：{TASK_TITLES[key]}，证据截图已保存。", "yellow")
        if self.sequence_mode:
            if self.current_index >= len(TASK_KEYS) - 1:
                # 最后一项：交给完成流程询问生成报告
                self._sequence_finished()
            else:
                self._ask_next()
        else:
            self.status_var.set(f"{TASK_TITLES[key]} 完成。")

    def take_screenshot(self, key):
        """截取 CMD 终端区当前内容作为证据图。"""
        try:
            from PIL import ImageGrab
            self.update_idletasks()
            x = self.term.winfo_rootx()
            y = self.term.winfo_rooty()
            w = self.term.winfo_width()
            h = self.term.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            path = os.path.join(self.report_dir, f"{key}.png")
            img.save(path)
            self.screenshots[key] = path
            self.log(f"截图已保存：{path}")
        except Exception as e:
            self.log(f"截图失败：{e}", "red")

    # ==================================================================
    # 消息队列分发
    # ==================================================================
    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()
                self._handle_message(msg_type, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_message(self, msg_type, p):
        if msg_type == "addr_both":
            self._handle_addr(p[0], p[1])
        elif msg_type == "signal_raw":
            self._handle_signal(p)
        elif msg_type == "ping_packet":
            self._handle_ping_packet(p)
        elif msg_type == "ping_summary":
            self._handle_ping_summary(p)
        elif msg_type == "roam_packet":
            self._handle_roam_packet(p)
        elif msg_type == "roam_event":
            self._handle_roam_event(p)
        elif msg_type == "roam_summary":
            self._handle_roam_summary(p)
        elif msg_type == "report_progress":
            self._handle_report_progress(p)
        elif msg_type == "report_done":
            self._handle_report_done(p)

    # ==================================================================
    # 报告数据组装
    # ==================================================================
    def _build_report_data(self):
        """把界面结果组装为报告生成器所需的数据结构。"""
        items = []

        # 1. 地址获取（无线网卡）
        addr_fields = []
        ad = self.wlan_adapter
        if ad:
            gateway = ad["ipv4_gateway"] or ad["gateway"] or "无"
            addr_fields = [
                {"name": "连接 SSID", "value": self.result_signal.get("ssid", "—")},
                {"name": "网卡名称", "value": ad["name"]},
                {"name": "获取方式", "value": ad["dhcp"] if ad["dhcp"] != "未知" else "DHCP 自动获取"},
                {"name": "IP 地址", "value": ad["ipv4"]},
                {"name": "子网掩码", "value": ad["mask"]},
                {"name": "默认网关", "value": gateway},
                {"name": "DNS 服务器", "value": ad["dns"] or "无"},
                {"name": "MAC 地址", "value": ad["mac"]},
            ]
        items.append({
            "key": "address", "title": "地址获取",
            "conclusion": "正常" if addr_fields else "未测",
            "fields": addr_fields,
            "images": [self.screenshots.get("address")],
        })

        # 2. 信号强度
        sig = self.result_signal
        sig_fields = []
        if sig:
            sig_fields = [
                {"name": "SSID", "value": sig.get("ssid", "—")},
                {"name": "频段", "value": sig.get("band", "—")},
                {"name": "信道", "value": str(sig.get("channel", "—"))},
                {"name": "信号强度", "value": f'{sig.get("signal_dbm", "—")} dBm（{sig.get("signal_per", "—")}%）'},
                {"name": "无线制式", "value": sig.get("standard", "—")},
                {"name": "协商速率", "value": f'接收 {sig.get("rx_rate", "—")} / 发送 {sig.get("tx_rate", "—")} Mbps'},
            ]
        items.append({
            "key": "signal", "title": "信号强度",
            "conclusion": sig.get("judge", "未测") if sig else "未测",
            "fields": sig_fields,
            "images": [self.screenshots.get("signal")],
        })

        # 3. 定点 Ping
        ping = self.result_ping
        ping_fields = []
        if ping:
            ping_fields = [
                {"name": "目标地址", "value": ping["target"]},
                {"name": "测试方式", "value": f"连续 ping {DEFAULT_COUNT} 包"},
                {"name": "发送包数", "value": str(ping["sent"])},
                {"name": "接收包数", "value": str(ping["received"])},
                {"name": "丢失包数", "value": str(ping["lost"])},
                {"name": "丢包率", "value": f'{ping["loss_rate"]}%'},
                {"name": "最小时延", "value": f'{ping["min_ms"]} ms'},
                {"name": "平均时延", "value": f'{ping["avg_ms"]} ms'},
                {"name": "最大时延", "value": f'{ping["max_ms"]} ms'},
                {"name": "抖动", "value": f'{ping["jitter_ms"]} ms'},
            ]
        items.append({
            "key": "ping", "title": "定点 ping 包测试",
            "conclusion": ping.get("judge", "未测") if ping else "未测",
            "fields": ping_fields,
            "images": [self.screenshots.get("ping")],
        })

        # 4. 无线漫游（持续 ping，手动停止）
        roam = self.result_roam
        roam_fields = []
        if roam:
            roam_fields = [
                {"name": "测试方式", "value": "ping -t 持续 Ping，现场手动停止"},
                {"name": "目标地址", "value": roam["target"]},
                {"name": "起始 AP / SSID", "value": roam["start_ap"]},
                {"name": "结束 AP / SSID", "value": roam["end_ap"]},
                {"name": "切换次数", "value": str(roam["switch_count"])},
                {"name": "发送 / 接收包数", "value": f'{roam["sent"]} / {roam["received"]}'},
                {"name": "过程丢包", "value": f'{roam["lost"]} 个（{roam["loss_rate"]}%）'},
                {"name": "业务中断时长", "value": f'{roam["max_gap"]} 秒'},
            ]
        items.append({
            "key": "roaming", "title": "无线漫游",
            "conclusion": roam.get("judge", "未测") if roam else "未测",
            "fields": roam_fields,
            "images": [self.screenshots.get("roaming")],
        })

        # 5. 网线距离及接口速率（单独测试项，未包含在本软件内）
        items.append({
            "key": "cable", "title": "网线距离及接口速率",
            "conclusion": "未测",
            "fields": [],
            "images": [],
            "remark": "本项为单独测试项，未包含在本软件内，需另行登录交换机/AP 网管界面或使用线缆测距仪测试。",
        })

        return {
            "flow_no": self.var_order.get().strip() or "未填写",
            "test_area": self.var_area.get().strip() or "未填写",
            "tester": self.var_person.get().strip() or "未填写",
            "generated_at": self.test_time or "未填写",
            "items": items,
        }

    # ==================================================================
    # 生成 Word 报告
    # ==================================================================
    def _open_report_dialog(self):
        """弹出模态“正在生成报告”加载窗，进度条滚动动画，禁止中途关闭。"""
        dlg = tk.Toplevel(self)
        dlg.title("正在生成报告")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        w, h = 380, 160
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        ttk.Label(dlg, text="正在生成 Word 测试报告，请稍候…",
                  font=("黑体", 12)).pack(pady=(22, 8))
        self.report_label = ttk.Label(dlg, text="正在创建报告文档…", foreground="#555")
        self.report_label.pack(pady=(0, 8))
        pb = ttk.Progressbar(dlg, mode="determinate", length=280, maximum=100, value=0)
        pb.pack(pady=6)
        # 生成过程中禁止点右上角关闭，避免后台线程与界面状态不一致
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)
        self.report_dlg = dlg
        self.report_pb = pb

    def _close_report_dialog(self):
        if self.report_dlg is not None:
            try:
                self.report_dlg.destroy()
            except Exception:
                pass
            self.report_dlg = None
            self.report_pb = None
            self.report_label = None

    def generate_report(self, auto=False):
        if not any([self.result_addr, self.result_signal, self.result_ping, self.result_roam]):
            messagebox.showinfo("提示", "暂无测试结果，请先执行测试。")
            return
        data = self._build_report_data()
        default_name = f'{data["flow_no"]}-无线测试报告.docx'
        path = filedialog.asksaveasfilename(
            title="保存测试报告", defaultextension=".docx",
            filetypes=[("Word 文档", "*.docx"), ("所有文件", "*.*")],
            initialfile=default_name,
        )
        if not path:
            # 用户取消保存：本次不清空，保留在界面
            return

        # 先显示加载动画，再把耗时的报告写入放到后台线程，避免界面假死
        self._open_report_dialog()

        def on_progress(pct, msg):
            self.msg_queue.put(("report_progress", (pct, msg)))

        def worker():
            try:
                import report_generator  # 延迟加载，避免启动时加载 docx 重依赖
                overall = report_generator.build_report(data, path, progress_cb=on_progress)
                self.msg_queue.put(("report_done", (True, path, overall)))
            except Exception as e:
                self.msg_queue.put(("report_done", (False, "", str(e))))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_report_progress(self, payload):
        pct, msg = payload
        if self.report_pb is not None:
            self.report_pb["value"] = pct
        if self.report_label is not None:
            self.report_label.config(text=msg)

    def _handle_report_done(self, payload):
        ok, path, msg = payload
        self._close_report_dialog()
        if ok:
            messagebox.showinfo("生成成功", f"测试报告已生成：\n{path}\n总体结论：{msg}")
            # 报告保存完成后，清空界面恢复初始状态
            self.reset_all()
        else:
            messagebox.showerror("生成失败", f"报告写入失败：{msg}")

    # ==================================================================
    # 清空界面，恢复初始状态
    # ==================================================================
    def reset_all(self):
        """本次测试结束后清空全部表单、结果、截图与状态，回到初始可再次录入的状态。"""
        self.var_order.set("")
        self.var_area.set("")
        self.var_person.set("")

        self.result_addr = []
        self.result_signal = {}
        self.result_ping = {}
        self.result_roam = {}
        self.wlan_adapter = None
        self.raw_addr = ""
        self.raw_signal = ""
        self.screenshots = {}

        for k in TASK_KEYS:
            self.set_task_status(k, "待执行")
        for k, var in self.summary_vars.items():
            var.set("—")

        self.clear_terminal()
        self.sequence_mode = False
        self.current_index = -1
        self.ping_stop = False
        self.roam_stop = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_next.config(state=tk.DISABLED)

        # 新一轮测试目录
        self.run_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report_dir = os.path.join(app_base_dir(), "reports", self.run_time)
        os.makedirs(self.report_dir, exist_ok=True)

        # 测试时间留空，待下次点击“开始测试”时刷新
        self.test_time = ""
        self._refresh_test_time_label()
        self.status_var.set("已复位。请填写流程单号、测试区域、测试人员后，点击“开始测试”。")

    # ==================================================================
    # 导出 TXT 记录（保留）
    # ==================================================================
    def export_txt(self):
        if not any([self.result_addr, self.result_signal, self.result_ping, self.result_roam]):
            messagebox.showinfo("提示", "暂无测试结果可导出，请先执行测试。")
            return
        data = self._build_report_data()
        path = filedialog.asksaveasfilename(
            title="保存测试记录", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="无线测试记录.txt",
        )
        if not path:
            return
        lines = ["无线网络测试记录", "=" * 40,
                 f"流程单号：{data['flow_no']}", f"测试区域：{data['test_area']}",
                 f"测试人员：{data['tester']}", f"测试时间：{data['generated_at']}", ""]
        for item in data["items"]:
            lines.append(item["title"])
            lines.append("-" * 40)
            for f in item["fields"]:
                lines.append(f"  {f['name']}：{f['value']}")
            lines.append(f"  结论：{item['conclusion']}")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            messagebox.showinfo("导出成功", f"测试记录已保存：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"写入失败：{e}")


if __name__ == "__main__":
    app = WifiTesterApp()
    app.mainloop()
