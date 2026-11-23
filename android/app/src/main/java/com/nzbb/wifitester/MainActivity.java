package com.nzbb.wifitester;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.format.Formatter;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.FileProvider;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * 无线测试工具主界面（安卓版）。
 * 模块：地址获取、信号强度、定点 Ping（100 包）、无线漫游（100 包），并可生成图文 HTML 测试报告。
 */
public class MainActivity extends AppCompatActivity {

    private WifiManager wifiManager;

    private EditText etOrder, etArea, etPerson;
    private TextView tvTime;
    private TextView tvAddr, tvSignal, tvPingResult, tvRoamResult;
    private EditText etPingTarget, etPingCount, etRoamTarget;
    private Button btnPingStart, btnRoamStart, btnReport;

    // 漫游持续 Ping 停止标志
    private volatile boolean roamStopped = false;
    private android.app.AlertDialog roamDialog;

    private final Handler uiHandler = new Handler(Looper.getMainLooper());
    private static final Pattern TIME_RE = Pattern.compile("time=([0-9.]+)\\s*ms");
    private static final SimpleDateFormat TIME_FMT = new SimpleDateFormat("yyyy年MM月dd日 HH:mm", Locale.getDefault());
    private static final SimpleDateFormat LOG_FMT = new SimpleDateFormat("HH:mm:ss", Locale.getDefault());

    // 各模块采集结果，供报告生成使用
    private final Map<String, String> addressData = new HashMap<>();
    private final Map<String, String> signalData = new HashMap<>();
    private final Map<String, String> pingData = new HashMap<>();
    private final Map<String, String> roamData = new HashMap<>();
    private final List<String> roamEvents = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        wifiManager = (WifiManager) getSystemService(WIFI_SERVICE);

        etOrder = findViewById(R.id.etOrder);
        etArea = findViewById(R.id.etArea);
        etPerson = findViewById(R.id.etPerson);
        tvTime = findViewById(R.id.tvTime);
        tvAddr = findViewById(R.id.tvAddr);
        tvSignal = findViewById(R.id.tvSignal);
        tvPingResult = findViewById(R.id.tvPingResult);
        tvRoamResult = findViewById(R.id.tvRoamResult);
        etPingTarget = findViewById(R.id.etPingTarget);
        etPingCount = findViewById(R.id.etPingCount);
        etRoamTarget = findViewById(R.id.etRoamTarget);
        btnPingStart = findViewById(R.id.btnPingStart);
        btnRoamStart = findViewById(R.id.btnRoamStart);
        btnReport = findViewById(R.id.btnReport);

        etPingCount.setText("100");
        tvTime.setText("测试时间：" + TIME_FMT.format(new Date()));

        findViewById(R.id.btnAddrRefresh).setOnClickListener(v -> refreshAddress());
        findViewById(R.id.btnSignalRefresh).setOnClickListener(v -> refreshSignal());
        btnPingStart.setOnClickListener(v -> startPingTest());
        btnRoamStart.setOnClickListener(v -> startRoamTest());
        btnReport.setOnClickListener(v -> generateReport());

        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 100);
        }

        refreshAddress();
        refreshSignal();
    }

    // ==================================================================
    // 模块一：地址获取
    // ==================================================================
    private void refreshAddress() {
        WifiInfo info = wifiManager.getConnectionInfo();
        android.net.DhcpInfo dhcp = wifiManager.getDhcpInfo();
        addressData.clear();
        String addrJudge = "未测";

        StringBuilder sb = new StringBuilder();
        String ssid = quote(info.getSSID());
        sb.append("SSID：").append(ssid).append("\n");
        sb.append("BSSID：").append(info.getBSSID()).append("\n");
        addressData.put("SSID", ssid);
        addressData.put("BSSID", info.getBSSID());

        if (dhcp != null) {
            String ip = Formatter.formatIpAddress(dhcp.ipAddress);
            String mask = Formatter.formatIpAddress(dhcp.netmask);
            String gw = Formatter.formatIpAddress(dhcp.gateway);
            String dns1 = Formatter.formatIpAddress(dhcp.dns1);
            sb.append("IP 地址：").append(ip).append("\n");
            sb.append("子网掩码：").append(mask).append("\n");
            sb.append("默认网关：").append(gw).append("\n");
            sb.append("DNS 1：").append(dns1).append("\n");
            addressData.put("IP 地址", ip);
            addressData.put("子网掩码", mask);
            addressData.put("默认网关", gw);
            addressData.put("DNS 服务器", dns1);
            etPingTarget.setText(gw);
            etRoamTarget.setText(gw);
            if (!"0.0.0.0".equals(ip)) addrJudge = "正常";
        }
        sb.append("MAC 地址：").append(info.getMacAddress() == null ? "不可用" : info.getMacAddress());
        addressData.put("结论", addrJudge);
        tvAddr.setText(sb.toString());
    }

    // ==================================================================
    // 模块二：信号强度
    // ==================================================================
    private void refreshSignal() {
        WifiInfo info = wifiManager.getConnectionInfo();
        signalData.clear();
        int rssi = info.getRssi();
        int freq = info.getFrequency();
        int channel = freqToChannel(freq);
        String band = freq < 3000 ? "2.4 GHz" : "5 GHz";
        String judge = judgeSignal(rssi);

        StringBuilder sb = new StringBuilder();
        sb.append("SSID：").append(quote(info.getSSID())).append("\n");
        sb.append("BSSID：").append(info.getBSSID()).append("\n");
        sb.append("频段：").append(band).append("\n");
        sb.append("信道：").append(channel > 0 ? String.valueOf(channel) : "未知").append("\n");
        sb.append("信号强度：").append(rssi).append(" dBm（").append(judge).append("）\n");
        sb.append("协商速率：").append(info.getLinkSpeed()).append(" Mbps\n");
        sb.append("制式：").append(getStandard(info));
        tvSignal.setText(sb.toString());

        signalData.put("SSID", quote(info.getSSID()));
        signalData.put("频段", band);
        signalData.put("信道", channel > 0 ? String.valueOf(channel) : "未知");
        signalData.put("信号强度", rssi + " dBm（" + judge + "）");
        signalData.put("协商速率", info.getLinkSpeed() + " Mbps");
        signalData.put("无线制式", getStandard(info));
        signalData.put("结论", judge);
    }

    private static int freqToChannel(int freq) {
        if (freq == 2484) return 14;
        if (freq >= 2412 && freq <= 2472) return (freq - 2412) / 5 + 1;
        if (freq >= 5170 && freq <= 5825) return (freq - 5170) / 5 + 34;
        return -1;
    }

    private static String judgeSignal(int rssi) {
        if (rssi >= -60) return "优";
        if (rssi >= -70) return "良";
        if (rssi >= -80) return "一般";
        return "差";
    }

    private static String getStandard(WifiInfo info) {
        int speed = info.getLinkSpeed();
        int freq = info.getFrequency();
        if (freq >= 5000 && speed > 86) return "802.11ac";
        if (speed > 72) return "802.11n";
        return "802.11a/b/g/n";
    }

    // ==================================================================
    // 模块三：定点 Ping
    // ==================================================================
    private void startPingTest() {
        String target = etPingTarget.getText().toString().trim();
        if (target.isEmpty()) {
            Toast.makeText(this, "请先填写目标地址", Toast.LENGTH_SHORT).show();
            return;
        }
        int count = parseIntSafe(etPingCount.getText().toString(), 100);
        btnPingStart.setEnabled(false);
        tvPingResult.setText("");

        new Thread(() -> {
            List<Packet> packets = new ArrayList<>();
            for (int i = 1; i <= count; i++) {
                Packet p = pingOnce(target);
                packets.add(p);
                final int seq = i;
                String record = "[" + LOG_FMT.format(new Date()) + "] 第" + seq + "包 "
                        + (p.ok ? ("时延 " + p.latency + " ms") : "请求超时/丢失")
                        + "　" + firstLine(p.raw);
                uiHandler.post(() -> tvPingResult.append(record + "\n"));
            }
            PingSummary sum = summarize(packets);

            pingData.clear();
            pingData.put("目标地址", target);
            pingData.put("测试方式", "连续 ping " + count + " 包");
            pingData.put("发送包数", String.valueOf(sum.sent));
            pingData.put("接收包数", String.valueOf(sum.received));
            pingData.put("丢失包数", String.valueOf(sum.lost));
            pingData.put("丢包率", sum.lossRate + "%");
            pingData.put("最小时延", sum.minMs == null ? "—" : sum.minMs + " ms");
            pingData.put("平均时延", sum.avgMs == null ? "—" : sum.avgMs + " ms");
            pingData.put("最大时延", sum.maxMs == null ? "—" : sum.maxMs + " ms");
            pingData.put("结论", sum.judge);

            String summary = "\n---- Ping 统计汇总 ----\n" + formatPingSummary(target, sum);
            uiHandler.post(() -> {
                btnPingStart.setEnabled(true);
                tvPingResult.append(summary);
            });
        }).start();
    }

    // ==================================================================
    // 模块四：无线漫游（持续长 Ping，用户手动停止）
    // ==================================================================
    private void startRoamTest() {
        String target = etRoamTarget.getText().toString().trim();
        if (target.isEmpty()) {
            Toast.makeText(this, "请先填写目标地址", Toast.LENGTH_SHORT).show();
            return;
        }
        roamStopped = false;
        btnRoamStart.setEnabled(false);
        tvRoamResult.setText("");
        roamEvents.clear();

        // 弹出停止控制窗：由用户确认结束 Ping 的时间
        android.app.AlertDialog.Builder builder = new android.app.AlertDialog.Builder(this);
        builder.setTitle("无线漫游测试进行中");
        builder.setMessage("正在持续 Ping（长 Ping），请沿漫游路径匀速移动；\n测试完成后点击下方按钮停止 Ping。");
        builder.setCancelable(false);
        builder.setPositiveButton("停止 Ping", (d, w) -> stopRoam());
        roamDialog = builder.show();

        new Thread(() -> {
            List<Packet> packets = new ArrayList<>();
            WifiInfo start = wifiManager.getConnectionInfo();
            String prevBssid = start.getBSSID();
            String startAp = quote(start.getSSID()) + " (" + start.getBSSID() + ")";
            String startEvent = LOG_FMT.format(new Date()) + " 起始关联：" + startAp;
            roamEvents.add(startEvent);
            uiHandler.post(() -> tvRoamResult.append(startEvent + "\n"));

            int switchCount = 0;
            long lastCheck = System.currentTimeMillis();

            // 持续发包，直到用户点击停止
            while (!roamStopped) {
                Packet p = pingOnce(target);
                packets.add(p);
                String record = "[" + LOG_FMT.format(new Date()) + "] 第" + packets.size() + "包 "
                        + (p.ok ? ("时延 " + p.latency + " ms") : "请求超时/丢失")
                        + "　" + firstLine(p.raw);
                uiHandler.post(() -> tvRoamResult.append(record + "\n"));

                long now = System.currentTimeMillis();
                if (now - lastCheck >= 2000) {
                    lastCheck = now;
                    WifiInfo cur = wifiManager.getConnectionInfo();
                    if (cur.getBSSID() != null && !cur.getBSSID().equals(prevBssid)) {
                        switchCount++;
                        String ev = LOG_FMT.format(new Date()) + " 漫游切换："
                                + quote(cur.getSSID()) + " (" + cur.getBSSID() + ") " + cur.getRssi() + " dBm";
                        roamEvents.add(ev);
                        prevBssid = cur.getBSSID();
                        uiHandler.post(() -> tvRoamResult.append("[事件] " + ev + "\n"));
                    }
                }
            }

            WifiInfo end = wifiManager.getConnectionInfo();
            String endAp = quote(end.getSSID()) + " (" + end.getBSSID() + ")";
            PingSummary sum = summarize(packets);
            long maxGap = 0;
            Long gapStart = null;
            for (Packet p : packets) {
                if (!p.ok) {
                    if (gapStart == null) gapStart = p.time;
                    else maxGap = Math.max(maxGap, p.time - gapStart);
                } else gapStart = null;
            }
            String judge;
            if (sum.sent == 0) judge = "未测";
            else if (sum.lost == 0) judge = "正常";
            else if (sum.lost <= 1 && maxGap <= 2000) judge = "可接受";
            else judge = "异常";

            roamData.clear();
            roamData.put("测试方式", "持续 Ping，现场手动停止");
            roamData.put("目标地址", target);
            roamData.put("起始 AP / SSID", startAp);
            roamData.put("结束 AP / SSID", endAp);
            roamData.put("切换次数", String.valueOf(switchCount));
            roamData.put("发送 / 接收包数", sum.sent + " / " + sum.received);
            roamData.put("过程丢包", sum.lost + "（" + sum.lossRate + "%）");
            roamData.put("业务中断时长", maxGap / 1000.0 + " 秒");
            roamData.put("结论", judge);

            StringBuilder sb = new StringBuilder();
            sb.append("\n---- 漫游汇总 ----\n");
            sb.append("起始 AP：").append(startAp).append("\n");
            sb.append("结束 AP：").append(endAp).append("\n");
            sb.append("切换次数：").append(switchCount).append("\n");
            sb.append("发送 / 接收：").append(sum.sent).append(" / ").append(sum.received).append("\n");
            sb.append("过程丢包：").append(sum.lost).append("（").append(sum.lossRate).append("%）\n");
            sb.append("最长中断：").append(maxGap / 1000.0).append(" 秒\n");
            sb.append("结论：").append(judge).append("\n");

            uiHandler.post(() -> {
                btnRoamStart.setEnabled(true);
                tvRoamResult.append(sb.toString());
            });
        }).start();
    }

    private void stopRoam() {
        roamStopped = true;
        if (roamDialog != null) {
            try { roamDialog.dismiss(); } catch (Exception ignored) {}
            roamDialog = null;
        }
    }

    // ==================================================================
    // Ping 底层执行与统计
    // ==================================================================
    private static class Packet {
        boolean ok;
        double latency;
        long time;
        String raw = "";
    }

    private Packet pingOnce(String target) {
        Packet p = new Packet();
        p.time = System.currentTimeMillis();
        StringBuilder out = new StringBuilder();
        Process process = null;
        try {
            // 合并 stderr 到 stdout，避免两个管道互相阻塞导致死锁
            ProcessBuilder pb = new ProcessBuilder("ping", "-c", "1", "-W", "1", target);
            pb.redirectErrorStream(true);
            process = pb.start();
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            while ((line = reader.readLine()) != null) out.append(line).append("\n");
            // 超时强制销毁，防止进程挂起导致一直发不出包
            if (!process.waitFor(3, TimeUnit.SECONDS)) {
                process.destroyForcibly();
            }
            String raw = out.toString().trim();
            p.raw = raw;
            Matcher m = TIME_RE.matcher(raw);
            if (m.find()) {
                p.ok = true;
                p.latency = Double.parseDouble(m.group(1));
            } else {
                p.ok = false;
                p.latency = -1;
            }
        } catch (Exception e) {
            p.ok = false;
            p.latency = -1;
            p.raw = "ping 执行异常：" + e.getMessage();
            if (process != null) {
                try { process.destroyForcibly(); } catch (Exception ignored) {}
            }
        }
        return p;
    }

    /** 取原始输出的第一行，用于界面逐包记录显示。 */
    private static String firstLine(String raw) {
        if (raw == null || raw.isEmpty()) return "";
        int idx = raw.indexOf('\n');
        return idx < 0 ? raw : raw.substring(0, idx).trim();
    }

    private static class PingSummary {
        int sent, received, lost;
        double lossRate;
        Double minMs, avgMs, maxMs;
        String judge;
    }

    private PingSummary summarize(List<Packet> packets) {
        PingSummary s = new PingSummary();
        s.sent = packets.size();
        List<Double> lat = new ArrayList<>();
        for (Packet p : packets) {
            if (p.ok) lat.add(p.latency); else s.lost++;
        }
        s.received = lat.size();
        s.lossRate = s.sent == 0 ? 0 : Math.round(s.lost * 10000.0 / s.sent) / 100.0;
        if (!lat.isEmpty()) {
            double min = lat.get(0), max = lat.get(0), sum = 0;
            for (double v : lat) { min = Math.min(min, v); max = Math.max(max, v); sum += v; }
            s.minMs = min; s.maxMs = max; s.avgMs = Math.round(sum / lat.size() * 100.0) / 100.0;
        }
        if (s.sent == 0) s.judge = "未测";
        else if (s.lost == 0) s.judge = "优";
        else if (s.lossRate <= 1) s.judge = "可接受";
        else s.judge = "异常";
        return s;
    }

    private String formatPingSummary(String target, PingSummary s) {
        StringBuilder sb = new StringBuilder();
        sb.append("目标：").append(target).append("\n");
        sb.append("发送：").append(s.sent).append("  接收：").append(s.received)
                .append("  丢失：").append(s.lost).append("  丢包率：").append(s.lossRate).append("%\n");
        if (s.received > 0) {
            sb.append("时延：最小 ").append(s.minMs).append(" ms / 平均 ")
                    .append(s.avgMs).append(" ms / 最大 ").append(s.maxMs).append(" ms\n");
        }
        sb.append("结论：").append(s.judge);
        return sb.toString();
    }

    // ==================================================================
    // 生成 Word(.docx) 测试报告（纯 Java 手写 zip+XML，无第三方依赖）
    // ==================================================================
    private static final String DOCX_MIME =
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

    private void generateReport() {
        if (addressData.isEmpty() && signalData.isEmpty() && pingData.isEmpty() && roamData.isEmpty()) {
            Toast.makeText(this, "暂无测试数据，请先执行测试", Toast.LENGTH_SHORT).show();
            return;
        }
        String order = etOrder.getText().toString().trim();
        String area = etArea.getText().toString().trim();
        String person = etPerson.getText().toString().trim();
        String time = TIME_FMT.format(new Date());

        File dir = new File(getExternalFilesDir(null), "reports");
        if (!dir.exists()) dir.mkdirs();
        String fileName = (order.isEmpty() ? "无线测试报告" : order) + ".docx";
        File file = new File(dir, fileName);

        // 等待对话框：后台生成期间提示用户，避免界面假死
        android.app.ProgressDialog wait = new android.app.ProgressDialog(this);
        wait.setTitle("正在生成报告");
        wait.setMessage("正在生成 Word 测试报告，请稍候…");
        wait.setCancelable(false);
        wait.show();

        new Thread(() -> {
            String error = null;
            try {
                writeDocx(file, order, area, person, time);
            } catch (Exception e) {
                error = e.getMessage();
            }
            final String err = error;
            final File out = file;
            uiHandler.post(() -> {
                wait.dismiss();
                if (err != null) {
                    Toast.makeText(this, "报告生成失败：" + err, Toast.LENGTH_LONG).show();
                    return;
                }
                // 弹出对话框：打开或分享
                android.app.AlertDialog.Builder builder = new android.app.AlertDialog.Builder(this);
                builder.setTitle("报告已生成（Word）");
                builder.setMessage("报告文件：\n" + out.getAbsolutePath());
                builder.setPositiveButton("打开报告", (d, w) -> openDocx(out));
                builder.setNeutralButton("分享报告", (d, w) -> shareDocx(out));
                builder.setNegativeButton("关闭", null);
                builder.show();
            });
        }).start();
    }

    private void writeDocx(File file, String order, String area, String person, String time) throws Exception {
        StringBuilder doc = new StringBuilder();
        doc.append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
        doc.append("<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">");
        doc.append("<w:body>");

        // 标题
        doc.append(docxPara("无线网络测试报告", true, 40, "center", "黑体"));

        // 基础信息表
        List<String[]> base = new ArrayList<>();
        base.add(new String[]{"流程单号", order.isEmpty() ? "未填写" : order});
        base.add(new String[]{"测试区域", area.isEmpty() ? "未填写" : area});
        base.add(new String[]{"测试人员", person.isEmpty() ? "未填写" : person});
        base.add(new String[]{"测试时间", time});
        doc.append(docxTable(base));

        // 概述（与电脑端报告口径一致）
        String areaText = area.isEmpty() ? "未填写" : area;
        String personText = person.isEmpty() ? "未填写" : person;
        doc.append(docxPara("本次测试区域为" + areaText + "，由" + personText + "现场实施。测试环境为局域网，"
                + "连通性测试目标均为网关及内网设备。测试内容包括地址获取、信号强度、定点 ping 包测试、"
                + "无线漫游四项；网线距离及接口速率为单独测试项，未包含在本软件内。"
                + "各项测试过程、结果分析与命令运行结果截图见下文。",
                false, 21, "left", "宋体"));

        // 四个分项 + 未测项
        doc.append(docxSection("address", "地址获取", addressData, ""));
        doc.append(docxSection("signal", "信号强度", signalData, ""));
        doc.append(docxSection("ping", "定点 ping 包测试", pingData, ""));
        doc.append(docxSection("roaming", "无线漫游", roamData, ""));
        doc.append(docxSection("cable", "网线距离及接口速率", new HashMap<>(),
                "本项为单独测试项，未包含在本软件内，需另行登录交换机/AP 网管界面或使用线缆测距仪测试。"));

        // 总体结论
        doc.append(docxPara("总体结论", true, 26, "left", "黑体"));
        doc.append(docxPara(overallConclusion(), true, 21, "left", "宋体"));

        // 签字栏
        doc.append(docxPara("测试人员签字：____________　　日期：____________", false, 21, "left", "宋体"));

        doc.append("</w:body></w:document>");

        String contentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                + "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                + "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                + "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                + "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
                + "</Types>";

        String rels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                + "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
                + "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
                + "</Relationships>";

        ZipOutputStream zos = new ZipOutputStream(new FileOutputStream(file),
                java.nio.charset.StandardCharsets.UTF_8);
        putEntry(zos, "[Content_Types].xml", contentTypes);
        putEntry(zos, "_rels/.rels", rels);
        putEntry(zos, "word/document.xml", doc.toString());
        zos.close();
    }

    private void putEntry(ZipOutputStream zos, String name, String content) throws Exception {
        ZipEntry entry = new ZipEntry(name);
        zos.putNextEntry(entry);
        zos.write(content.getBytes("UTF-8"));
        zos.closeEntry();
    }

    private String docxPara(String text, boolean bold, int halfPt, String align, String font) {
        StringBuilder sb = new StringBuilder();
        sb.append("<w:p><w:pPr><w:jc w:val=\"").append(align).append("\"/></w:pPr>");
        sb.append("<w:r><w:rPr><w:rFonts w:eastAsia=\"").append(font).append("\"/>");
        if (bold) sb.append("<w:b/>");
        sb.append("<w:sz w:val=\"").append(halfPt).append("\"/></w:rPr>");
        sb.append("<w:t xml:space=\"preserve\">").append(escXml(text)).append("</w:t></w:r></w:p>");
        return sb.toString();
    }

    private String docxTable(List<String[]> rows) {
        StringBuilder sb = new StringBuilder();
        sb.append("<w:tbl><w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/>");
        sb.append("<w:tblBorders>");
        String[] borders = {"top", "left", "bottom", "right", "insideH", "insideV"};
        for (String b : borders) {
            sb.append("<w:").append(b).append(" w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"999999\"/>");
        }
        sb.append("</w:tblBorders></w:tblPr>");
        sb.append("<w:tblGrid><w:gridCol w:w=\"2600\"/><w:gridCol w:w=\"5600\"/></w:tblGrid>");
        for (String[] row : rows) {
            sb.append("<w:tr>");
            sb.append(docxCell(row[0], "2600", true));
            sb.append(docxCell(row[1], "5600", false));
            sb.append("</w:tr>");
        }
        sb.append("</w:tbl>");
        return sb.toString();
    }

    private String docxCell(String text, String width, boolean bold) {
        StringBuilder sb = new StringBuilder();
        sb.append("<w:tc><w:tcPr><w:tcW w:w=\"").append(width).append("\" w:type=\"dxa\"/></w:tcPr>");
        sb.append("<w:p><w:r><w:rPr><w:rFonts w:eastAsia=\"宋体\"/>");
        if (bold) sb.append("<w:b/>");
        sb.append("<w:sz w:val=\"21\"/></w:rPr>");
        sb.append("<w:t xml:space=\"preserve\">").append(escXml(text)).append("</w:t></w:r></w:p></w:tc>");
        return sb.toString();
    }

    /** 各分项标准测试目的与过程方法，与电脑端报告模板一致。 */
    private String[] itemProfile(String key) {
        switch (key) {
            case "address":
                return new String[]{
                        "验证无线终端关联目标 SSID 后，能否通过 DHCP 正常获取 IP 地址、子网掩码、默认网关与 DNS 服务器，确认终端已接入局域网且地址配置正确。",
                        "终端连接目标无线网络后，后台执行 ipconfig /all 查看无线网卡 IPv4 地址、掩码、网关、DNS 与 MAC，核对 IP 与网关是否处于同一网段；命令输出见本项截图证据。"
                };
            case "signal":
                return new String[]{
                        "测试当前点位无线信号覆盖质量，通过信号强度（RSSI）、频段、信道、无线制式与协商速率评估链路状况。",
                        "在测试点位连接目标 SSID，后台执行 netsh wlan show interfaces 读取 RSSI、频段、信道、协商速率等参数，读数稳定后记录；命令输出见本项截图证据。"
                };
            case "ping":
                return new String[]{
                        "测试定点位置无线链路的连通性、时延与丢包情况，评估无线链路稳定性。",
                        "在固定点位关联 WiFi，后台对网关或内网服务器/AC 地址连续 ping 100 包，统计发送、接收、丢失包数、丢包率及最小、平均、最大时延与抖动；命令输出见本项截图证据。"
                };
            case "roaming":
                return new String[]{
                        "验证终端移动过程中能否在相邻 AP 间自动平滑切换，漫游期间业务是否连续，有无掉线、重连或长时间卡顿。",
                        "终端关联起始 AP 后执行 ping -t 持续 ping 网关，沿漫游路径匀速移动，由测试人员现场手动停止；记录切换前后 AP/SSID、过程丢包与中断时长；命令输出与切换事件见本项截图证据。"
                };
            default:
                return new String[]{
                        "验证 AP 与交换机间网线通断、线缆长度及端口协商速率、双工模式。",
                        "本项为单独测试项，未包含在本软件内，需登录交换机/AP 网管界面或使用线缆测距仪另行测试。"
                };
        }
    }

    private String docxSection(String key, String title, Map<String, String> data, String remark) {
        StringBuilder sb = new StringBuilder();
        sb.append(docxPara(title, true, 26, "left", "黑体"));
        String conclusion = data.isEmpty() ? "未测" : data.get("结论");
        if (conclusion == null) conclusion = "未测";
        sb.append(docxPara("测试结论：" + conclusion, true, 21, "left", "宋体"));

        String[] pm = itemProfile(key);
        sb.append(docxPara("测试目的", true, 22, "left", "黑体"));
        sb.append(docxPara(pm[0], false, 21, "left", "宋体"));
        sb.append(docxPara("测试过程与方法", true, 22, "left", "黑体"));
        sb.append(docxPara(pm[1], false, 21, "left", "宋体"));
        sb.append(docxPara("测试结果分析", true, 22, "left", "黑体"));
        sb.append(docxPara(buildResultDesc(data, conclusion), false, 21, "left", "宋体"));

        List<String[]> rows = new ArrayList<>();
        for (Map.Entry<String, String> e : data.entrySet()) {
            if ("结论".equals(e.getKey())) continue;
            rows.add(new String[]{e.getKey(), e.getValue()});
        }
        if (!rows.isEmpty()) sb.append(docxTable(rows));

        if (remark != null && !remark.isEmpty()) {
            sb.append(docxPara("备注：" + remark, false, 21, "left", "宋体"));
        }
        return sb.toString();
    }

    /** 生成结果分析文字，口径与电脑端报告一致。 */
    private String buildResultDesc(Map<String, String> data, String conclusion) {
        StringBuilder pairs = new StringBuilder();
        for (Map.Entry<String, String> e : data.entrySet()) {
            if ("结论".equals(e.getKey())) continue;
            String v = e.getValue() == null ? "" : e.getValue().trim();
            if (!v.isEmpty()) pairs.append(e.getKey()).append("为").append(v).append("；");
        }
        String detail = pairs.toString();
        if (detail.endsWith("；")) detail = detail.substring(0, detail.length() - 1);

        if ("未测".equals(conclusion)) {
            String t = "本次未取得该项有效测试数据，暂无法判定测试结果。";
            if (!detail.isEmpty()) t += "现有记录：" + detail + "。";
            return t;
        }
        if ("异常".equals(conclusion)) {
            return detail.isEmpty() ? "测试结果存在异常，需排查整改后复测。"
                    : "测试结果存在异常，现场记录：" + detail + "。需排查整改后复测。";
        }
        if ("可接受".equals(conclusion)) {
            return detail.isEmpty() ? "测试结果基本可用，存在需复核的观察项。"
                    : "测试结果基本可用，现场记录：" + detail + "。相关未显示项建议后续补充复核。";
        }
        return detail.isEmpty() ? "经现场测试，各项指标详见下表，整体满足局域网无线接入要求。"
                : "经现场测试，各项指标记录如下：" + detail + "；整体满足局域网无线接入要求。";
    }

    private String overallConclusion() {
        List<String> all = new ArrayList<>();
        all.add(addressData.get("结论"));
        all.add(signalData.get("结论"));
        all.add(pingData.get("结论"));
        all.add(roamData.get("结论"));
        if (all.contains("异常")) return "存在异常，需整改复测";
        if (all.contains(null) || all.contains("未测")) return "部分项目未测试，结论不完整";
        if (all.contains("可接受")) return "基本通过，存在观察项";
        return "测试通过";
    }

    private void openDocx(File file) {
        Intent intent = new Intent(Intent.ACTION_VIEW);
        Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", file);
        intent.setDataAndType(uri, DOCX_MIME);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(this, "暂无可用应用打开 Word 报告，可在文件管理中查看", Toast.LENGTH_SHORT).show();
        }
    }

    private void shareDocx(File file) {
        Intent intent = new Intent(Intent.ACTION_SEND);
        Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", file);
        intent.setType(DOCX_MIME);
        intent.putExtra(Intent.EXTRA_STREAM, uri);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(Intent.createChooser(intent, "分享测试报告"));
        } catch (Exception e) {
            Toast.makeText(this, "分享失败：" + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    // ==================================================================
    // 工具方法
    // ==================================================================
    private static int parseIntSafe(String text, int def) {
        try { return Integer.parseInt(text.trim()); } catch (Exception e) { return def; }
    }

    private static String quote(String ssid) {
        if (ssid == null) return "";
        return ssid.replaceAll("^\"|\"$", "");
    }

    private static String escXml(String text) {
        if (text == null) return "";
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
