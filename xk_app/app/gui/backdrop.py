# -*- coding: utf-8 -*-
"""天幕：整幅背景由程序生成，不依赖任何外部图片。

为什么不用照片：

  · 安装包要对外分发，随手搜来的图有授权问题；自己生成则完全没有
  · 主色刚换成淡紫，现成照片对不上色，硬调色又容易发脏
  · 窗口尺寸任意可拖，矢量绘制不会拉伸变形、不会糊
  · 体积为零，启动不用解码

如果确实想换成真实照片（比如校园风景图），把图片放到
`xk_app/assets/backdrop.jpg`（或 .png），`paint_sky()` 会**优先用它**，
按 cover 方式居中裁切。代码不用改。

生成的部分分五层：

  1. 竖向夜空渐变（深紫 → 近黑）
  2. 三团缓慢漂移的极光色块（薰衣草 / 暮粉 / 蓝紫）
  3. 低空辉光
  4. 星点（固定随机种子，数量随高度增加）
  5. 同心弧纹 —— 全站的重复母题，从图标到天幕到空状态都用它

第 2、4 层的相位由调用方传入并随时间推进，这就是「动」的来源。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPen, QPixmap,
                           QRadialGradient)

from .theme import C

# 生成用的固定种子：每次运行星点位置一致，不会闪
_SEED = 20240915

_photo_cache: QPixmap | None = None
_photo_probed = False

PHOTO_NAMES = ("backdrop.jpg", "backdrop.jpeg", "backdrop.png", "backdrop.webp")

# 天幕的几种「心情」。
# 每页换一种 —— 五页共用同一张背景的话，翻过去几乎没有「换了个地方」的感觉。
# 都在淡紫这一族里变：只调极光的位置、浓度、星点密度和辉光色，不跳色。
VARIANTS = {
    # 默认：均衡的紫罗兰
    "violet": {"ys_band": (0.30, 0.72, 1.15), "ys_panel": (0.20, 0.34, 0.72),
               "alphas": (58, 38, 30), "stars": 1.0, "top_shift": 0},
    # 偏冷：蓝紫更重、星更多
    "cool":   {"ys_band": (0.16, 0.58, 1.30), "ys_panel": (0.14, 0.30, 0.64),
               "alphas": (46, 28, 50), "stars": 1.6, "top_shift": 96,
               "c1": "#7C86E8", "c3": "#5E6BD6", "glow": "#CFD8FF",
               "glow_a": 40},
    # 偏暖：暮粉当主角
    "warm":   {"ys_band": (0.36, 0.82, 1.06), "ys_panel": (0.24, 0.40, 0.80),
               "alphas": (40, 54, 24), "stars": 0.8, "top_shift": 78,
               "c1": "#C58BE0", "c2": "#F0A8C4", "glow": "#FFD9E4",
               "glow_a": 58},
    # 沉下去：极光压低、更暗、星更密（用于「监控」这种要盯着的页面）
    "deep":   {"ys_band": (0.46, 0.96, 1.40), "ys_panel": (0.34, 0.52, 0.94),
               "alphas": (34, 22, 24), "stars": 1.9, "top_shift": -18,
               "glow_a": 30},
    # 玫瑰紫：介于 violet 与 warm 之间
    "rose":   {"ys_band": (0.24, 0.66, 1.22), "ys_panel": (0.18, 0.36, 0.76),
               "alphas": (50, 48, 32), "stars": 1.2, "top_shift": 64,
               "c1": "#B98BE6", "c3": "#8E7BE4", "glow": "#F3C9DE",
               "glow_a": 50},
}


def backdrop_image() -> QPixmap | None:
    """如果 assets 下放了真实背景图就用它，否则返回 None。"""
    global _photo_cache, _photo_probed
    if _photo_probed:
        return _photo_cache
    _photo_probed = True
    try:
        from ..runtime import find_asset
        for name in PHOTO_NAMES:
            p = find_asset(name)
            if not p:
                continue
            pm = QPixmap(p)
            if not pm.isNull():
                _photo_cache = pm
                break
    except Exception:
        _photo_cache = None
    return _photo_cache


def _blob(p: QPainter, cx: float, cy: float, r: float, color: str, alpha: int):
    g = QRadialGradient(QPointF(cx, cy), r)
    c0 = QColor(color)
    c0.setAlpha(alpha)
    cm = QColor(color)
    cm.setAlpha(int(alpha * 0.42))
    c1 = QColor(color)
    c1.setAlpha(0)
    g.setColorAt(0.00, c0)
    g.setColorAt(0.42, cm)
    g.setColorAt(1.00, c1)
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(cx, cy), r, r)


def _draw_cover(p: QPainter, pm: QPixmap, w: int, h: int):
    """把照片按 cover 方式铺满并居中裁切。"""
    if pm.width() <= 0 or pm.height() <= 0:
        return
    scale = max(w / pm.width(), h / pm.height())
    tw, th = pm.width() * scale, pm.height() * scale
    p.drawPixmap(
        QRectF((w - tw) / 2.0, (h - th) / 2.0, tw, th), pm,
        QRectF(0, 0, pm.width(), pm.height()))


def _paint_generated(p: QPainter, w: int, h: int, phase: float, stars: bool,
                     variant: str = "violet"):
    p.setRenderHint(QPainter.Antialiasing, True)

    # 「横条」和「竖版」要分别处理：同一条公式套在 1360×128 的顶栏和
    # 660×700 的登录面板上，得到的是一团糊 vs 一圈糊。
    band = h < w * 0.45
    v = VARIANTS.get(variant, VARIANTS["violet"])

    # 1. 夜空
    g = QLinearGradient(0, 0, 0, h)
    top = QColor(C["sky_top"])
    if v.get("top_shift"):
        top = top.lighter(v["top_shift"])
    if band:
        g.setColorAt(0.00, top)
        g.setColorAt(0.62, QColor(C["sky_mid"]))
        g.setColorAt(1.00, QColor(C["sky_bottom"]))
    else:
        g.setColorAt(0.00, top)
        g.setColorAt(0.30, QColor(C["sky_top"]))
        g.setColorAt(0.70, QColor(C["sky_mid"]))
        g.setColorAt(1.00, QColor(C["sky_bottom"]))
    p.fillRect(0, 0, w, h, g)

    r_blob = h * 1.62 if band else max(w, h) * 0.55

    # 4. 星点先画，让后面的极光把它们压暗一部分（有远近）
    if stars and h > 96:
        rnd = random.Random(_SEED)
        n = int(max(8, min(80, int(w * h / 9000))) * v.get("stars", 1.0))
        top_f = 0.62 if band else 0.86
        p.setPen(Qt.NoPen)
        for i in range(n):
            x = rnd.random() * w
            y = rnd.random() * h * top_f
            r = 0.7 + rnd.random() * 1.1
            tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(phase * 1.7 + i * 1.31))
            a = int((55 + rnd.random() * 105) * tw)
            p.setBrush(QColor(255, 255, 255, max(0, min(200, a))))
            p.drawEllipse(QPointF(x, y), r, r)

    # 2. 极光：三团，缓慢反向漂移。位置/颜色/浓度按 variant 变。
    a1 = (phase * 0.17) % 2.0 - 1.0
    a2 = (phase * 0.11 + 0.6) % 2.0 - 1.0
    a3 = (phase * 0.23 + 1.3) % 2.0 - 1.0
    ys = v["ys_band"] if band else v["ys_panel"]
    alphas = v["alphas"]
    cols = (v.get("c1") or C["sky_aurora_a"],
            v.get("c2") or C["sky_aurora_b"],
            v.get("c3") or C["sky_aurora_c"])
    _blob(p, w * (0.30 + 0.10 * a1), h * ys[0], r_blob, cols[0], alphas[0])
    _blob(p, w * (0.76 + 0.09 * a2), h * ys[1], r_blob * 0.82, cols[1], alphas[1])
    _blob(p, w * (0.52 + 0.12 * a3), h * ys[2], r_blob * 0.94, cols[2], alphas[2])

    # 3. 低空辉光
    gg = QRadialGradient(QPointF(w * 0.5, h * (1.35 if band else 1.06)),
                         max(w, h) * (0.9 if band else 0.72))
    gc = QColor(v.get("glow") or C["sky_glow"])
    gc.setAlpha(v.get("glow_a", 46 if band else 54))
    g0 = QColor(v.get("glow") or C["sky_glow"])
    g0.setAlpha(0)
    gg.setColorAt(0.0, gc)
    gg.setColorAt(1.0, g0)
    p.setPen(Qt.NoPen)
    p.fillRect(0, 0, w, h, gg)


def _paint_arcs(p: QPainter, w: int, h: int, *, clip_h: int | None = None,
                band: bool = False):
    """同心弧纹 —— 全站的重复母题。

    横条上用扁椭圆（只露出很平的一段，像地平线）；竖版上用**正圆**，
    否则超扁的椭圆在面板里几乎就是几条横贯全宽的直线，看着像划痕。
    """
    p.save()
    if clip_h is not None:
        p.setClipRect(0, 0, w, int(clip_h))
    p.setBrush(Qt.NoBrush)

    if band:
        cx, cy = w * 0.5, h * 1.90
        rx_ratio, step, a0 = 2.60, 0.30, 26
        r0 = 0.52
    else:
        cx, cy = w * 0.5, h * 1.10
        rx_ratio, step, a0 = 1.00, 0.23, 15
        r0 = 0.34

    for i in range(12):
        ry = h * (r0 + i * step)
        a = int(a0 - i * 1.35)
        if a <= 2:
            break
        pen = QPen(QColor(255, 255, 255, a))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), ry * rx_ratio, ry)
    p.restore()


def paint_sky(p: QPainter, w: int, h: int, phase: float = 0.0, *,
              arcs: bool = True, stars: bool = True,
              fade_to: str | None = None, fade_h: int = 0,
              variant: str = "violet") -> None:
    """画一整块天幕。`phase` 随时间推进 → 极光漂移、星点明灭。

    variant：见 VARIANTS，决定这一页的天幕「心情」。

    fade_to / fade_h：底部 `fade_h` 像素化进 `fade_to` 这个颜色。
    **必须在两个颜色之间插值之外另想办法** —— 直接插值会在中间调留下一道灰带；
    这里是把目标色用 alpha 逐渐盖上去。这个坑一次改版里踩过两次。
    """
    if w <= 0 or h <= 0:
        return

    photo = backdrop_image()
    if photo is not None:
        _draw_cover(p, photo, w, h)
        # 照片上压一层深色，保证白字可读
        veil = QLinearGradient(0, 0, 0, h)
        veil.setColorAt(0.0, QColor(20, 13, 43, 130))
        veil.setColorAt(1.0, QColor(20, 13, 43, 205))
        p.fillRect(0, 0, w, h, veil)
    else:
        _paint_generated(p, w, h, phase, stars, variant)

    if arcs:
        band = h < w * 0.45
        _paint_arcs(p, w, h, clip_h=(h - fade_h) if fade_h else None, band=band)

    if fade_to and fade_h > 0:
        fg = QLinearGradient(0, h - fade_h, 0, h)
        base = QColor(fade_to)
        for pos, a in ((0.00, 0), (0.38, 96), (0.72, 208), (1.00, 255)):
            c = QColor(base)
            c.setAlpha(a)
            fg.setColorAt(pos, c)
        p.fillRect(0, int(h - fade_h), w, fade_h, fg)
