"""Render the TwoWorlds design diagram to matching PNG and editable SVG."""
from pathlib import Path
from html import escape
import math

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 2400, 1900
BG = "#0B1220"
PANEL = "#111D30"
CARD = "#17273E"
STROKE = "#30455E"
WHITE = "#EDF4FC"
MUTED = "#A9BDD3"
BLUE = "#74B6FA"
GREEN = "#72DBB6"
GOLD = "#EBC479"
PURPLE = "#B7A3F7"
img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<title>TwoWorlds 双人 AI 互动剧本平台：设计架构 v0.2</title>',
       '<desc>展示双人客户端、FastAPI、确定性规则、角色投影、原子存档、受限 AI 文本流程、内容发布和后续语音边界。</desc>',
       f'<rect width="{W}" height="{H}" fill="{BG}"/>']
font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in font_cache:
        font_cache[key] = ImageFont.truetype(
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc", size
        )
    return font_cache[key]


def text(x, y, value, size=26, color=WHITE, bold=False, anchor="left", max_width=None):
    f = font(size, bold)
    width = draw.textlength(value, font=f)
    if max_width is not None and width > max_width:
        raise ValueError(f"Text too wide ({width:.0f}>{max_width}): {value}")
    left = x - width / 2 if anchor == "center" else x
    draw.text((left, y), value, font=f, fill=color, anchor="lt")
    weight = 700 if bold else 400
    svg.append(f'<text x="{left:.2f}" y="{y}" dominant-baseline="text-before-edge" '
               f'font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" font-size="{size}" '
               f'font-weight="{weight}" fill="{color}">{escape(value)}</text>')


def box(x, y, w, h, fill=CARD, stroke=STROKE, radius=20, dashed=False):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill,
                           outline=None if dashed else stroke, width=2)
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
               f'fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
    if dashed:
        # Straight dashed sides keep the future-only border visibly distinct in PNG.
        for a, b in [((x + radius, y), (x + w - radius, y)),
                     ((x + radius, y + h), (x + w - radius, y + h)),
                     ((x, y + radius), (x, y + h - radius)),
                     ((x + w, y + radius), (x + w, y + h - radius))]:
            line([a, b], stroke, 2, dashed=True)


def line(points, color=MUTED, width=3, dashed=False, arrow=False):
    if dashed:
        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if not length:
                continue
            for start in range(0, int(length), 17):
                end = min(start + 9, length)
                draw.line([(a[0] + dx * start / length, a[1] + dy * start / length),
                           (a[0] + dx * end / length, a[1] + dy * end / length)], fill=color, width=width)
    else:
        draw.line(points, fill=color, width=width, joint="curve")
    pts = " ".join(f"{x},{y}" for x, y in points)
    dash = ' stroke-dasharray="9 8"' if dashed else ""
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" '
               f'stroke-linejoin="round" stroke-linecap="round"{dash}/>')
    if arrow:
        a, b = points[-2:]
        theta = math.atan2(b[1] - a[1], b[0] - a[0])
        head = [b,
                (b[0] - 15 * math.cos(theta - .45), b[1] - 15 * math.sin(theta - .45)),
                (b[0] - 15 * math.cos(theta + .45), b[1] - 15 * math.sin(theta + .45))]
        draw.polygon(head, fill=color)
        svg.append(f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in head)}" fill="{color}"/>')


def label(x, y, value, color=MUTED, size=22):
    f = font(size)
    width = draw.textlength(value, font=f)
    box(x - width / 2 - 9, y - 4, width + 18, size + 14, BG, BG, 6)
    text(x, y, value, size, color, anchor="center")


def heading(x, y, n, title, color):
    box(x, y + 3, 43, 37, fill=color, stroke=color, radius=8)
    text(x + 21.5, y + 7, n, 22, BG, True, "center")
    text(x + 59, y, title, 30, WHITE, True)


def small_card(x, y, w, h, title, lines, color=WHITE):
    box(x, y, w, h)
    text(x + 22, y + 17, title, 27, color, True, max_width=w - 44)
    for i, value in enumerate(lines):
        text(x + 22, y + 54 + 30 * i, value, 22, MUTED, max_width=w - 44)


# Header and legend.
text(64, 47, "TwoWorlds", 62, WHITE, True)
text(465, 62, "双人 AI 互动剧本平台", 42, WHITE, True)
text(64, 128, "多剧本独立存档 · 非对称合作 · 跨设备继续", 28, MUTED)
box(1928, 66, 408, 51, fill="#203047", stroke="#3A526F", radius=25)
text(2132, 78, "设计架构 v0.2  /  尚未实现", 23, MUTED, anchor="center")

# Player layer.
box(560, 200, 1280, 210, PANEL)
text(600, 220, "01   双人客户端", 30, BLUE, True)
text(1590, 228, "Vue 3 + TypeScript + PWA", 24, MUTED, anchor="center")
small_card(600, 274, 550, 106, "玩家 A · 独立身份与角色", ["iPhone / Android / 电脑浏览器"], BLUE)
small_card(1250, 274, 550, 106, "玩家 B · 独立身份与角色", ["各自线索、装置与 NPC 私聊"], BLUE)
text(64, 237, "同一个故事", 32, WHITE, True)
text(64, 285, "不同的观察与操作能力", 27, MUTED)
text(64, 329, "双方合作，程序确认结果", 27, MUTED)

# Panels.
box(64, 480, 440, 700, PANEL)
heading(92, 506, "02", "内容准备与发布", GOLD)
small_card(92, 584, 384, 115, "原创剧本与世界设定", ["灯塔：光路与反向供电", "星轨：功率与信号协同"], GOLD)
small_card(92, 756, 384, 115, "内容校验与规则测试", ["场景引用、前置、可解性", "角色可见性、结局轨迹"], GOLD)
small_card(92, 928, 384, 115, "不可变版本内容包", ["每份存档绑定剧本版本", "首版精确读取，无向量依赖"], GOLD)
line([(284, 699), (284, 756)], GOLD, arrow=True)
line([(284, 871), (284, 928)], GOLD, arrow=True)
text(92, 1094, "谜底与规则只留在服务端", 24, GOLD, max_width=384)
text(92, 1133, "此链路不调用玩家的私聊数据", 22, MUTED, max_width=384)

box(560, 480, 1280, 700, PANEL)
small_card(600, 524, 1200, 96, "03   FastAPI · 身份认证与成员授权", ["HTTP 查询与命令  /  WebSocket 首帧鉴权  /  统一权限检查"], BLUE)
small_card(600, 700, 1200, 106, "04   应用服务 · 操作编排", ["服务器确定角色 → 识别幂等回执 → 验证版本 → 执行规则或生成文本"], WHITE)
small_card(600, 884, 550, 112, "05   确定性规则引擎", ["角色、前置、装置、因果与结局", "纯 Python · 不依赖模型判定"], GOLD)
small_card(1250, 884, 550, 112, "06   按角色裁剪可见数据", ["公共事实 + 本人线索与对话", "同一投影供 HTTP、WS 和 AI"], BLUE)
box(600, 1064, 1200, 84)
text(630, 1080, "07   仓储接口 · 数据库原子提交（CAS）", 28, GREEN, True)
text(630, 1119, "同一次写入：状态 + 版本 + 幂等回执；AI 文本提交前再次检查版本", 23, MUTED, max_width=1140)

# Main flow arrows.
line([(1200, 410), (1200, 524)], BLUE, arrow=True)
label(1200, 450, "HTTPS / WSS", BLUE)
line([(1200, 620), (1200, 700)], BLUE, arrow=True)
label(1200, 647, "已认证请求")
line([(875, 806), (875, 884)], GOLD, arrow=True)
label(875, 838, "机关操作", GOLD)
line([(1525, 806), (1525, 884)], BLUE, arrow=True)
label(1525, 838, "查询 / 文本上下文", BLUE)
line([(875, 996), (875, 1064)], GREEN, arrow=True)
label(875, 1023, "规则结果", GREEN)
line([(1525, 1064), (1525, 996)], BLUE, arrow=True)
label(1525, 1023, "读取已确认存档", BLUE)
line([(504, 940), (600, 940)], GOLD, arrow=True)

# Per-player snapshot return bus, separate from private AI context below.
line([(1800, 930), (1860, 930), (1860, 327), (1840, 327)], BLUE, arrow=True)
label(1665, 445, "个人快照 · 断线全量恢复", BLUE)

# AI column.
box(1900, 480, 436, 700, PANEL)
heading(1928, 506, "08", "受限 AI 文本流程", PURPLE)
small_card(1928, 584, 380, 115, "当前玩家可见上下文", ["场景设定 + 本人近期对话", "不含伙伴秘密与完整谜底"], PURPLE)
small_card(1928, 760, 380, 91, "LangGraph 工作流", ["整理上下文 → 生成 → 校验"], PURPLE)
small_card(1928, 912, 380, 107, "模型 Provider", ["默认示例 / 可配置 Qwen 等", "超时、并发、长度与降级"], PURPLE)
box(1928, 1080, 380, 66, fill="#2A2440", stroke="#655387")
text(2118, 1099, "输出：仅本人可见文本", 25, PURPLE, True, "center")
line([(2118, 699), (2118, 760)], PURPLE, arrow=True)
line([(2118, 851), (2118, 912)], PURPLE, arrow=True)
line([(2118, 1019), (2118, 1080)], PURPLE, arrow=True)
line([(1800, 968), (1880, 968), (1880, 640), (1928, 640)], PURPLE, arrow=True)
line([(1928, 1113), (1880, 1113), (1880, 1236), (1580, 1236), (1580, 1148)], PURPLE, arrow=True)
label(1713, 1250, "版本复查后保存本人文本", PURPLE, 21)

# Persistence.
box(560, 1310, 1280, 260, PANEL, stroke="#3A6E62")
heading(600, 1335, "09", "正式存档与记忆 · MongoDB", GREEN)
small_card(600, 1403, 350, 111, "身份与房间", ["恢复摘要 / 期限会话", "A、B 固定成员与邀请"], GREEN)
small_card(1025, 1403, 350, 111, "每房间 × 每剧本独立档", ["世界状态 / 版本 / 回执", "装置、共同选择与里程碑"], GREEN)
small_card(1450, 1403, 350, 111, "本人对话与公开回顾", ["私聊按角色隔离", "正式事实可用于恢复"], GREEN)
text(600, 1534, "SQLite 仅作显式本地演示；生产使用 MongoDB，不自动降级。", 23, MUTED)
line([(1200, 1148), (1200, 1310)], GREEN, arrow=True)
label(1200, 1210, "原子保存 / 持久化恢复", GREEN)

# Quality is deliberately a side capability, not an online dependency.
box(64, 1310, 440, 260, PANEL)
heading(92, 1335, "10", "质量与可观测性", MUTED)
text(92, 1406, "规则、权限与并发测试", 25, WHITE, max_width=384)
text(92, 1450, "Prompt 版本 / 离线评估", 25, WHITE, max_width=384)
text(92, 1494, "脱敏耗时 / 错误 / 用量", 25, WHITE, max_width=384)
text(92, 1538, "本地报告；Opik 可选接入", 22, MUTED, max_width=384)

box(1900, 1310, 436, 260, PANEL, stroke="#65748B", dashed=True)
heading(1928, 1335, "11", "后续语音扩展", MUTED)
text(1928, 1406, "玩家通话：WebRTC / LiveKit", 24, MUTED, max_width=380)
text(1928, 1450, "NPC 语音：ASR / TTS", 24, MUTED, max_width=380)
text(1928, 1494, "独立成员鉴权，首版 disabled", 23, MUTED, max_width=380)
text(1928, 1538, "玩家通话不默认交给 AI", 23, MUTED, max_width=380)

# Bottom principle and legend.
box(64, 1644, 2272, 143, fill="#162439", stroke="#344C69")
text(96, 1667, "一条完整游戏操作链", 27, WHITE, True)
text(96, 1714, "玩家操作 → 身份与成员校验 → 幂等与版本 → 规则裁决 → 原子落库 → 双方收到各自快照", 31, WHITE, max_width=2208)
text(64, 1823, "核心边界：程序决定事实与结局；AI 负责表达；服务端始终掌握唯一权威进度。", 27, GOLD)
text(64, 1865, "实线为首版设计流程  ·  虚线框为后续扩展  ·  可观测性为辅助能力  ·  2026-10-26", 21, MUTED)

svg.append("</svg>")
png_path = OUT / "twoworlds-architecture-v0.2.png"
svg_path = OUT / "twoworlds-architecture-v0.2.svg"
img.save(png_path)
svg_path.write_text("\n".join(svg), encoding="utf-8")
print(png_path)
print(svg_path)
print(f"Rendered {W} x {H}; all bounded text passed width checks.")
