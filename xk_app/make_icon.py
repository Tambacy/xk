# -*- coding: utf-8 -*-
"""生成应用图标（学校紫圆角方块 + 白色"选"字），多尺寸打包成 .ico。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)

PURPLE = (123, 45, 142)
PURPLE_DARK = (94, 31, 110)
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


def make(size: int) -> Image.Image:
    scale = 4                      # 先画大图再缩小，边缘更平滑
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角方块 + 竖向渐变
    r = int(S * 0.22)
    for y in range(S):
        t = y / max(1, S - 1)
        col = tuple(int(PURPLE[i] * (1 - t) + PURPLE_DARK[i] * t) for i in range(3))
        d.line([(0, y), (S, y)], fill=col + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=255)
    img.putalpha(mask)

    # 白色"选"字
    font = find_font(int(S * 0.62))
    d = ImageDraw.Draw(img)
    text = "选"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1] - S * 0.02),
           text, font=font, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


imgs = [make(s) for s in SIZES]
ico = OUT / "app.ico"
imgs[0].save(ico, format="ICO", sizes=[(s, s) for s in SIZES])
imgs[0].save(OUT / "app.png")
print(f"图标已生成：{ico}  ({ico.stat().st_size} 字节)")
print("尺寸：", SIZES)
