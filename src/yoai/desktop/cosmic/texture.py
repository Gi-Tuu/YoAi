"""程序化星球贴图 · 移植参考 build_planet.py 的思路，用纯 Qt 实现（零 PIL 依赖）。

关键（参考原文）：产出 512px 可水平无缝平铺的等距圆柱投影纹理；
球面光照/明暗界线/大气辉光由绘制时叠加，所以纹理转而光不转（物理正确）。

- texture_moon()：灰岩底 + 多尺度噪声 + 月海暗斑 + 细碎撞击坑（不规则，不画规则圆）。
- texture_sun()：橙底 + 湍流 + 不规则黑子 + 亮斑耀斑。
- 无缝：左右各 40px 向内线性融合到均值，x=0 与 x=511 相等，平铺自转无接缝。
"""

from __future__ import annotations

import random

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

W = H = 512
SEED = 20261107


def _noise(scale: int, blur: int, rng: random.Random) -> QImage:
    """低分辨率白噪声 → 低分辨率盒模糊 → 平滑放大为连续地貌层（横向周期性）。

    模糊必须在低分辨率图上做：512² 上做半径 12 的盒模糊要 600 万次访问/层，
    在 8×4 上做只要几百次，放大时双线性插值自然平滑，视觉等价且快三个数量级。
    """
    n = max(2, int(W / scale))
    m = max(2, n // 2)
    small = QImage(n, m, QImage.Format.Format_RGB32)
    for y in range(m):
        for x in range(n):
            small.setPixel(x, y, qGray(rng.randint(0, 255)))
    small.setPixel(n - 1, 0, small.pixel(0, 0))
    if blur > 0:
        small = _box_blur(small, max(1, min(3, blur // max(1, scale // 4))))
    return small.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def _lum(img: QImage, x: int, y: int) -> int:
    c = img.pixelColor(x, y)
    return (c.red() + c.green() + c.blue()) // 3


def _box_blur(img: QImage, radius: int) -> QImage:
    """轻量盒式模糊（可分离，够用），避免依赖 PIL 高斯。"""
    if radius <= 0:
        return img
    w, h = img.width(), img.height()
    tmp = QImage(w, h, QImage.Format.Format_RGB32)
    out = QImage(w, h, QImage.Format.Format_RGB32)
    for y in range(h):
        for x in range(w):
            s = n = 0
            for dx in range(-radius, radius + 1):
                xx = x + dx
                if 0 <= xx < w:
                    s += _lum(img, xx, y)
                    n += 1
            v = s // max(1, n)
            tmp.setPixel(x, y, qGray(v))
    for y in range(h):
        for x in range(w):
            s = n = 0
            for dy in range(-radius, radius + 1):
                yy = y + dy
                if 0 <= yy < h:
                    s += (tmp.pixel(yy, x) & 0xFF)
                    n += 1
            v = s // max(1, n)
            out.setPixel(x, y, qGray(v))
    return out


def qGray(v: int) -> int:
    v = max(0, min(255, int(v)))
    return (255 << 24) | (v << 16) | (v << 8) | v


def _compose(base: tuple[int, int, int], layers: list[tuple[QImage, float, tuple[float, float, float]]]) -> QImage:
    out = QImage(W, H, QImage.Format.Format_RGB32)
    for y in range(H):
        for x in range(W):
            r, g, b = base
            for img, amp, tint in layers:
                v = (_lum(img, x, y) - 128) / 128.0
                r = max(0, min(255, int(r + amp * v * tint[0])))
                g = max(0, min(255, int(g + amp * v * tint[1])))
                b = max(0, min(255, int(b + amp * v * tint[2])))
            out.setPixel(x, y, (255 << 24) | (r << 16) | (g << 8) | b)
    return out


def _blotches(img: QImage, mask: QImage, threshold: int,
              dark: tuple[int, int, int], amount: float) -> None:
    """用连续噪声阈值生成不规则暗斑（月海/黑子），不画规则圆。"""
    for y in range(H):
        for x in range(W):
            v = _lum(mask, x, y)
            if v <= threshold:
                continue
            a = ((v - threshold) / (255 - threshold)) ** 1.4 * amount
            c = img.pixelColor(x, y)
            img.setPixel(x, y, QColor(
                int(c.red() * (1 - a) + dark[0] * a),
                int(c.green() * (1 - a) + dark[1] * a),
                int(c.blue() * (1 - a) + dark[2] * a),
            ).rgb())


def _seamless(img: QImage) -> QImage:
    """左右各 40px 向内线性融合到均值，使 x=0 与 x=511 完全相等。"""
    band = 40
    for y in range(H):
        left = [img.pixelColor(x, y) for x in range(band)]
        right = [img.pixelColor(W - 1 - x, y) for x in range(band)]
        for x in range(band):
            t = (band - x) / band
            a, b = left[x], right[x]
            avg = ((a.red() + b.red()) // 2, (a.green() + b.green()) // 2, (a.blue() + b.blue()) // 2)
            img.setPixel(x, y, QColor(
                int(a.red() * (1 - t) + avg[0] * t),
                int(a.green() * (1 - t) + avg[1] * t),
                int(a.blue() * (1 - t) + avg[2] * t)).rgb())
            img.setPixel(W - 1 - x, y, QColor(
                int(b.red() * (1 - t) + avg[0] * t),
                int(b.green() * (1 - t) + avg[1] * t),
                int(b.blue() * (1 - t) + avg[2] * t)).rgb())
    return img


def texture_moon() -> QImage:
    rng = random.Random(SEED)
    big = _noise(64, 12, rng)
    img = _compose((150, 146, 138), [
        (big, 40, (1, 1, 1)),
        (_noise(19, 5, rng), 24, (1, 1, 1)),
        (_noise(6, 1, rng), 13, (1, 1, 1)),
    ])
    _blotches(img, big, 138, (86, 84, 80), 0.55)          # 月海
    fines = _noise(9, 2, rng)
    inv = QImage(W, H, QImage.Format.Format_Grayscale8)
    for y in range(H):
        for x in range(W):
            inv.setPixel(x, y, qGray(255 - _lum(fines, x, y)))
    _blotches(img, inv, 176, (104, 101, 96), 0.30)        # 撞击坑
    return _seamless(img)


def texture_sun() -> QImage:
    rng = random.Random(SEED + 1)
    turb = _noise(30, 6, rng)
    img = _compose((238, 130, 50), [
        (turb, 62, (1.0, 0.96, 0.52)),
        (_noise(11, 2, rng), 44, (1.0, 0.9, 0.45)),
        (_noise(3.5, 1, rng), 27, (1.0, 0.86, 0.4)),
    ])
    spots = _noise(22, 3, rng)
    inv = QImage(W, H, QImage.Format.Format_Grayscale8)
    for y in range(H):
        for x in range(W):
            inv.setPixel(x, y, qGray(255 - _lum(spots, x, y)))
    _blotches(img, inv, 168, (150, 56, 20), 0.42)         # 黑子
    flare = _noise(14, 2, rng)
    for y in range(H):
        for x in range(W):
            v = _lum(flare, x, y)
            if v > 196:
                a = (v - 196) / 59 * 0.55
                c = img.pixelColor(x, y)
                img.setPixel(x, y, QColor(
                    min(255, int(c.red() + (255 - c.red()) * a)),
                    min(255, int(c.green() + (226 - c.green()) * a)),
                    min(255, int(c.blue() + (150 - c.blue()) * a))).rgb())
    return _seamless(img)


# 模块级缓存（贴图生成较慢，只算一次）
_CACHE: dict[str, QPixmap] = {}


def planet_tile(kind: str) -> QPixmap:
    if kind not in _CACHE:
        img = texture_moon() if kind == "moon" else texture_sun()
        _CACHE[kind] = QPixmap.fromImage(img)
    return _CACHE[kind]
