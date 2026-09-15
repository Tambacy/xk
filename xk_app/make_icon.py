# -*- coding: utf-8 -*-
"""生成应用图标（深墨绿圆角方块 + 白色「选」字），多尺寸打包成 .ico。

配色与界面完全同一套：渐变两端 #1B5A36 → #0C2A19 就是窗口顶部那条
Hero 带的两端。任务栏、桌面快捷方式、开始菜单、安装向导用的都是这张图，
必须和界面一个颜色 —— 否则会出现「图标是紫的、界面是绿的」这种脱节。

弧纹和界面里的画法一致（同心椭圆），在 256/128/64 上能看出来，
到 16px 自然糊掉，不会影响小尺寸下的辨识度。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)

TOP = (27, 90, 54)        # #1B5A36  Hero 带顶端
BOTTOM = (10, 35, 19)     # #0A2313  Hero 带底端
WHITE = (255, 255, 255)

SIZES = [256, 128, 64, 48, 32, 24, 16]


def find_font(size):
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "segoeuib.ttf"):
        for base in (r"C:\Windows\Fonts",):
            p = Path(base) / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue
    return ImageFont.load_default()


def _radial(img: Image.Image, cx, cy, r, color, alpha):
    """在 img 上叠一层径向柔光（PIL 没有现成的，用同心圆近似）。"""
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    steps = 48
    for i in range(steps, 0, -1):
        t = i / steps
        rr = r * t
        a = int(alpha * (1 - t) ** 1.6)
        if a <= 0:
            continue
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))
    return Image.alpha_composite(img, ov)


def make(size: int) -> Image.Image:
    scale = 4                      # 先画大图再缩小，边缘更平滑
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 底：竖向渐变（和 Hero 带同一对端点色）。
    # 这里刻意不画弧纹 —— 同心椭圆在方块里几乎就是横贯全宽的几条直线，
    # 戳在「选」字上像划痕。图标在 16px 下要干净，装饰留给界面。
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    d = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / max(1, S - 1)
        col = tuple(int(TOP[i] * (1 - t) + BOTTOM[i] * t) for i in range(3))
        d.line([(0, y), (S, y)], fill=col + (255,))

    # 顶部柔光，让上沿亮起来
    grad = _radial(grad, S * 0.40, -S * 0.24, S * 1.05, (255, 255, 255), 58)

    # 圆角裁切
    r = int(S * 0.22)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=255)
    img.paste(grad, (0, 0), mask)
    img.putalpha(mask)

    # 白色「选」字
    font = find_font(int(S * 0.60))
    d = ImageDraw.Draw(img)
    text = "选"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1] - S * 0.015),
           text, font=font, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


imgs = [make(s) for s in SIZES]
ico = OUT / "app.ico"
imgs[0].save(ico, format="ICO", sizes=[(s, s) for s in SIZES])
imgs[0].save(OUT / "app.png")
print(f"图标已生成：{ico}  ({ico.stat().st_size} 字节)")
print("尺寸：", SIZES)
