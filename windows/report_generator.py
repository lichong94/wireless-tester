# -*- coding: utf-8 -*-
"""
无线测试 Word 报告生成器
依据软件内采集的测试数据与 CMD 结果截图，生成结构化 .docx 报告。
报告结构：标题 → 基础信息表 → 测试概述 → 分项章节（目的/方法/结果分析/参数表/截图证据/备注）
          → 总体结论 → 签字栏。
依赖：python-docx、Pillow。
"""

from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

try:
    from PIL import Image
except ImportError:
    Image = None


# 各分项标准测试目的与过程方法
ITEM_PROFILES = {
    "address": {
        "purpose": "验证无线终端关联目标 SSID 后，能否通过 DHCP 正常获取 IP 地址、子网掩码、默认网关与 DNS 服务器，确认终端已接入局域网且地址配置正确。",
        "method": "终端连接目标无线网络后，后台执行 ipconfig /all 查看无线网卡 IPv4 地址、掩码、网关、DNS 与 MAC，核对 IP 与网关是否处于同一网段；命令输出见本项截图证据。",
    },
    "signal": {
        "purpose": "测试当前点位无线信号覆盖质量，通过信号强度（RSSI）、频段、信道、无线制式与协商速率评估链路状况。",
        "method": "在测试点位连接目标 SSID，后台执行 netsh wlan show interfaces 读取 RSSI、频段、信道、协商速率等参数，读数稳定后记录；命令输出见本项截图证据。",
    },
    "ping": {
        "purpose": "测试定点位置无线链路的连通性、时延与丢包情况，评估无线链路稳定性。",
        "method": "在固定点位关联 WiFi，后台对网关或内网服务器/AC 地址连续 ping 100 包，统计发送、接收、丢失包数、丢包率及最小、平均、最大时延与抖动；命令输出见本项截图证据。",
    },
    "roaming": {
        "purpose": "验证终端移动过程中能否在相邻 AP 间自动平滑切换，漫游期间业务是否连续，有无掉线、重连或长时间卡顿。",
        "method": "终端关联起始 AP 后执行 ping -t 持续 ping 网关，沿漫游路径匀速移动，由测试人员现场手动停止；记录切换前后 AP/SSID、过程丢包与中断时长；命令输出与切换事件见本项截图证据。",
    },
    "cable": {
        "purpose": "验证 AP 与交换机间网线通断、线缆长度及端口协商速率、双工模式。",
        "method": "本项为单独测试项，未包含在本软件内，需登录交换机/AP 网管界面或使用线缆测距仪另行测试。",
    },
}


def _set_font(run, font_name="宋体", size=10.5, bold=False):
    """设置文字字体并指定中文东亚字体，避免 Word 中文回退乱码。"""
    run.font.name = font_name
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def _add_paragraph(doc, text, font_name="宋体", size=10.5, bold=False, align=None, space_after=6):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    _set_font(run, font_name, size, bold)
    return p


def _style_table(table):
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER


def _prepare_image(image_path):
    """图片体积控制：宽度超 1600 像素等比缩小，非 RGB 转 RGB，返回可插入路径。"""
    if Image is None:
        return image_path
    p = Path(image_path)
    with Image.open(p) as picture:
        if picture.width > 1600:
            height = round(picture.height * 1600 / picture.width)
            picture = picture.resize((1600, height), Image.LANCZOS)
        if picture.mode != "RGB":
            picture = picture.convert("RGB")
        out = p.with_name(f"{p.stem}_conv.jpg")
        picture.save(out, "JPEG", quality=82, optimize=True)
    return out


def _build_result_desc(item):
    """结果分析文字：优先用显式描述，否则按结论与参数组织叙述。"""
    desc = str(item.get("result_desc", "")).strip()
    if desc:
        return desc
    conclusion = item.get("conclusion", "未测")
    pairs = [f"{f['name']}为{f['value']}" for f in item.get("fields", []) if str(f.get("value", "")).strip()]
    detail = "；".join(pairs)
    if conclusion == "未测":
        text = "本次未取得该项有效测试数据，暂无法判定测试结果。"
        if detail:
            text += f"现有记录：{detail}。"
        return text
    if conclusion == "异常":
        return f"测试结果存在异常，现场记录：{detail}。需排查整改后复测。" if detail else "测试结果存在异常，需排查整改后复测。"
    if conclusion == "可接受":
        return f"测试结果基本可用，现场记录：{detail}。相关未显示项建议后续补充复核。" if detail else "测试结果基本可用，存在需复核的观察项。"
    return f"经现场测试，各项指标记录如下：{detail}；整体满足局域网无线接入要求。" if detail else "经现场测试，各项指标详见下表，整体满足局域网无线接入要求。"


def _add_item_section(doc, item, base_dir):
    """写入单个分项章节。"""
    _add_paragraph(doc, item["title"], font_name="黑体", size=13, bold=True, space_after=4)
    _add_paragraph(doc, f"测试结论：{item.get('conclusion', '未测')}", size=10.5, bold=True)

    profile = ITEM_PROFILES.get(item.get("key", ""), {})
    purpose = str(item.get("purpose", "")).strip() or profile.get("purpose", "")
    method = str(item.get("method", "")).strip() or profile.get("method", "")
    if purpose:
        _add_paragraph(doc, "测试目的", font_name="黑体", size=11, bold=True, space_after=2)
        _add_paragraph(doc, purpose, size=10.5)
    if method:
        _add_paragraph(doc, "测试过程与方法", font_name="黑体", size=11, bold=True, space_after=2)
        _add_paragraph(doc, method, size=10.5)

    _add_paragraph(doc, "测试结果分析", font_name="黑体", size=11, bold=True, space_after=2)
    _add_paragraph(doc, _build_result_desc(item), size=10.5)

    # 参数表
    fields = item.get("fields", [])
    if fields:
        table = doc.add_table(rows=len(fields) + 1, cols=2)
        _style_table(table)
        for cell, text in zip([table.cell(0, 0), table.cell(0, 1)], ["测试参数", "测试结果"]):
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            _set_font(run, "宋体", 10.5, True)
        for row_index, f in enumerate(fields, start=1):
            for cell, text, bold in (
                (table.cell(row_index, 0), str(f.get("name", "")), True),
                (table.cell(row_index, 1), str(f.get("value", "")), False),
            ):
                cell.text = ""
                run = cell.paragraphs[0].add_run(text)
                _set_font(run, "宋体", 10.5, bold)
        doc.add_paragraph()

    # 截图证据
    images = item.get("images", [])
    if images:
        _add_paragraph(doc, "测试截图（命令运行结果证据）", font_name="黑体", size=11, bold=True, space_after=2)
        for image_name in images:
            if not image_name:
                continue
            image_path = Path(image_name)
            if not image_path.is_absolute():
                image_path = base_dir / image_name
            if image_path.exists():
                insert_path = _prepare_image(image_path)
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(str(insert_path), width=Cm(14))
            else:
                _add_paragraph(doc, f"［截图缺失：{image_name}］", size=10.5)
    else:
        _add_paragraph(doc, "本次未提供该项测试截图。", size=10.5)

    remark = item.get("remark", "").strip()
    if remark:
        _add_paragraph(doc, f"备注：{remark}", size=10.5)
    doc.add_paragraph()


def _summarize(ordered_items, overall_conclusion):
    if str(overall_conclusion).strip():
        return str(overall_conclusion).strip()
    conclusions = [i.get("conclusion", "未测") for i in ordered_items]
    if any(c == "异常" for c in conclusions):
        return "存在异常，需整改复测"
    if any(c == "未测" for c in conclusions):
        return "部分项目未测试，结论不完整"
    if any(c == "可接受" for c in conclusions):
        return "基本通过，存在观察项"
    return "测试通过"


def build_report(data, out_path, progress_cb=None):
    """
    组装并保存 Word 报告，返回总体结论。
    progress_cb(percent, message)：可选进度回调，percent 为 0~100 的真实阶段进度。
    """
    def _report(pct, msg):
        if progress_cb:
            try:
                progress_cb(int(pct), str(msg))
            except Exception:
                pass

    _report(0, "正在创建报告文档…")
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # 标题
    _add_paragraph(doc, "无线网络测试报告", font_name="黑体", size=20, bold=True,
                   align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)

    generated_at = str(data.get("generated_at", "")).strip()
    if not generated_at:
        generated_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    # 基础信息表
    rows = [
        ("流程单号", data.get("flow_no", "未填写")),
        ("测试区域", data.get("test_area", "未填写")),
        ("测试人员", data.get("tester", "未填写")),
        ("测试时间", generated_at),
    ]
    info_table = doc.add_table(rows=len(rows), cols=2)
    _style_table(info_table)
    for i, (name, value) in enumerate(rows):
        info_table.cell(i, 0).width = Cm(4)
        info_table.cell(i, 1).width = Cm(12)
        for cell, text, bold in ((info_table.cell(i, 0), name, True), (info_table.cell(i, 1), value, False)):
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            _set_font(run, "宋体", 10.5, bold)
    doc.add_paragraph()

    # 测试概述
    _add_paragraph(doc, "测试概述", font_name="黑体", size=13, bold=True, space_after=4)
    overview = (
        f"本次测试区域为{data.get('test_area', '未填写')}，由{data.get('tester', '未填写')}现场实施。"
        "测试环境为局域网，连通性测试目标均为网关及内网设备。测试内容包括地址获取、信号强度、"
        "定点 ping 包测试、无线漫游四项；网线距离及接口速率为单独测试项，未包含在本软件内。"
        "各项测试过程、结果分析与命令运行结果截图见下文。"
    )
    _add_paragraph(doc, overview, size=10.5)
    doc.add_paragraph()
    _report(15, "基础信息已写入，开始写入分项测试…")

    base_dir = Path(out_path).parent
    items = data.get("items", [])
    total = len(items)
    for idx, item in enumerate(items):
        title = item.get("title", f"第{idx + 1}项")
        _report(15 + int(70 * idx / total) if total else 15, f"正在写入分项：{title}")
        _add_item_section(doc, item, base_dir)
        _report(15 + int(70 * (idx + 1) / total) if total else 85, f"已完成分项：{title}")

    # 总体结论
    _report(92, "正在生成总体结论与签字栏…")
    overall = _summarize(items, data.get("overall_conclusion", ""))
    _add_paragraph(doc, "总体结论", font_name="黑体", size=13, bold=True, space_after=4)
    _add_paragraph(doc, overall, size=10.5, bold=True)
    doc.add_paragraph()

    # 签字栏
    sign = doc.add_table(rows=1, cols=2)
    sign.alignment = WD_TABLE_ALIGNMENT.CENTER
    run_left = sign.cell(0, 0).paragraphs[0].add_run("测试人员签字：____________")
    run_right = sign.cell(0, 1).paragraphs[0].add_run("日期：____________")
    _set_font(run_left, "宋体", 10.5)
    _set_font(run_right, "宋体", 10.5)

    _report(98, "正在保存 Word 文档…")
    doc.save(str(out_path))
    _report(100, "报告已保存")
    return overall
