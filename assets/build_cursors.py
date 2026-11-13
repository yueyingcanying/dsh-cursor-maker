# -*- coding: utf-8 -*-
"""dsh-cursor-maker / build_cursors.py

Build a complete 16-role Windows cursor scheme out of ONE picture.

The four roles people actually look at every day are drawn from the picture:

    arrow        the artwork fills the tile, a small accent arrow sits on top
    help         the accent arrow plus a round badge with the artwork
    busy         the artwork inside a ring, the ring spins over 10 frames
    appstarting  a small accent arrow plus a badge with a thin spinning arc

The remaining twelve roles carry the classic glyphs shipped in the template
folder, so the scheme stays consistent while never looking "unfinished".

Everything is rasterised at 8x and downsampled with Lanczos, so 32/48/64 px
variants all stay crisp. Animation frames are written as RIFF/ACON `.ani`
with `cSteps == cFrames` (a cSteps of 0 makes Windows reject the whole file
and silently fall back to the stock pointer).
"""
import argparse
import json
import math
import os
import shutil
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

SS = 8
SIZES = (32, 48, 64)

NAVY = (16, 22, 52, 255)
WHITE = (255, 255, 255, 255)

GENERATED = ("arrow.cur", "help.cur", "busy.ani", "appstarting.ani")
TEMPLATE_ROLES = (
    "cross.cur", "ibeam.cur", "pen.cur", "no.cur", "sizens.cur", "sizewe.cur",
    "sizenwse.cur", "sizenesw.cur", "sizeall.cur", "uparrow.cur", "hand.cur",
    "pin.cur",
)
HOTSPOT = {"arrow": (2, 2), "help": (2, 2), "appstarting": (2, 2), "busy": (16, 16)}

# Filled in by main() from --accent / artwork sampling.
BRAND = (77, 107, 254, 255)
BRAND_L = (150, 172, 255, 255)
BRAND_D = (30, 44, 160, 255)


# ------------------------------------------------------------------ geometry ---
def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def norm(v):
    L = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / L, v[1] / L)


def bbox_area(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def offset_poly(pts, d, sign=1, limit=3.5):
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        e1, e2 = norm(sub(p1, p0)), norm(sub(p2, p1))
        n1 = (e1[1] * sign, -e1[0] * sign)
        n2 = (e2[1] * sign, -e2[0] * sign)
        dot = n1[0] * n2[0] + n1[1] * n2[1]
        if 1.0 + dot < 1e-4:
            ox, oy = n1[0] * d, n1[1] * d
        else:
            k = d / (1.0 + dot)
            ox, oy = (n1[0] + n2[0]) * k, (n1[1] + n2[1]) * k
            L = math.hypot(ox, oy)
            if L > abs(d) * limit:
                s = abs(d) * limit / L
                ox, oy = ox * s, oy * s
        out.append((p1[0] + ox, p1[1] + oy))
    return out


def grow_poly(pts, d):
    a = offset_poly(pts, d, 1)
    b = offset_poly(pts, d, -1)
    return a if bbox_area(a) > bbox_area(b) else b


def dilate(mask, r):
    if r < 0.5:
        return mask
    return mask.filter(ImageFilter.GaussianBlur(r)).point(lambda v: 255 if v >= 40 else 0)


# ------------------------------------------------------------------- drawing ---
class Canvas(object):
    def __init__(self, size):
        self.size = size
        self.k = size / 32.0
        self.px = size * SS
        self.img = Image.new("RGBA", (self.px, self.px), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def T(self, p):
        return (p[0] * self.k * SS, p[1] * self.k * SS)

    def TP(self, pts):
        return [self.T(p) for p in pts]

    def tw(self, units):
        return units * self.k * SS

    def mask(self):
        return Image.new("L", (self.px, self.px), 0)

    def md(self, m):
        return ImageDraw.Draw(m)

    def grad(self, c0, c1, diag=0.0):
        w = h = self.px
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        t = np.clip((yy + xx * diag) / (1.0 + diag), 0, 1)[..., None]
        a = np.array(c0[:3], dtype=np.float32)[None, None, :]
        b = np.array(c1[:3], dtype=np.float32)[None, None, :]
        rgb = (a * (1 - t) + b * t).astype(np.uint8)
        alpha = np.full((h, w, 1), 255, dtype=np.uint8)
        return Image.fromarray(np.concatenate([rgb, alpha], axis=2), "RGBA")

    def paint_mask(self, m, fill, white=1.1, navy=0.7):
        if navy > 0:
            self.img.paste(Image.new("RGBA", self.img.size, NAVY), (0, 0),
                           dilate(m, self.tw(white + navy)))
        if white > 0:
            self.img.paste(Image.new("RGBA", self.img.size, WHITE), (0, 0),
                           dilate(m, self.tw(white)))
        if isinstance(fill, Image.Image):
            self.img.paste(fill, (0, 0), m)
        else:
            self.img.paste(Image.new("RGBA", self.img.size, fill), (0, 0), m)

    def paint_poly(self, pts, fill, white=1.1, navy=0.7):
        if navy > 0:
            self.d.polygon(self.TP(grow_poly(pts, white + navy)), fill=NAVY)
        if white > 0:
            self.d.polygon(self.TP(grow_poly(pts, white)), fill=WHITE)
        m = self.poly_mask(pts)
        if isinstance(fill, Image.Image):
            self.img.paste(fill, (0, 0), m)
        else:
            self.img.paste(Image.new("RGBA", self.img.size, fill), (0, 0), m)

    def poly_mask(self, pts):
        m = self.mask()
        self.md(m).polygon(self.TP(pts), fill=255)
        return m

    def ell_mask(self, cx, cy, rx, ry):
        m = self.mask()
        self.md(m).ellipse([self.T((cx - rx, cy - ry)), self.T((cx + rx, cy + ry))], fill=255)
        return m

    def cap_mask(self, p0, p1, w):
        m = self.mask()
        md = self.md(m)
        a, b = self.T(p0), self.T(p1)
        md.line([a, b], fill=255, width=max(1, int(round(w * self.k * SS))))
        r = w * self.k * SS / 2.0
        for c in (a, b):
            md.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=255)
        return m

    def union(self, *masks):
        out = np.array(masks[0])
        for m in masks[1:]:
            out = np.maximum(out, np.array(m))
        return Image.fromarray(out.astype(np.uint8))

    def out(self):
        return self.img.resize((self.size, self.size), Image.LANCZOS)


ARROW = [(0, 0), (0, 19.8), (4.1, 15.2), (6.9, 23.5), (10.4, 21.9), (7.6, 13.6), (13.3, 13.6)]


def arrow_pts(s=0.90, org=(2.2, 2.2)):
    return [(p[0] * s + org[0], p[1] * s + org[1]) for p in ARROW]


def arc_mask(c, cx, cy, R, w, phase, n, span=0.74, ccw=False):
    steps = 30
    segs = []
    spin = phase * (2 * math.pi / n) * (-1 if ccw else 1)
    for i in range(steps):
        if i / steps > span:
            continue
        t0 = 2 * math.pi * (i / steps) + spin
        t1 = 2 * math.pi * ((i + 1) / steps) + spin
        segs.append(c.cap_mask((cx + math.cos(t0) * R, cy + math.sin(t0) * R),
                               (cx + math.cos(t1) * R, cy + math.sin(t1) * R), w))
    m = segs[0]
    for s in segs[1:]:
        m = c.union(m, s)
    return m


# --------------------------------------------------------------- cur / ani io ---
def to_cur_image(img, hx, hy):
    w, h = img.size
    px = img.load()
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)
    stride = ((w + 31) // 32) * 4
    and_mask = b"\x00" * (stride * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    data = header + xor + and_mask
    entry = struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, hx, hy, len(data), 0)
    return entry, data


def read_cur_images(path):
    """Read a .cur back as `[(image, hotspot)]`, newest frame data included."""
    data = open(path, "rb").read()
    count = struct.unpack("<H", data[4:6])[0]
    out = []
    for i in range(count):
        entry = data[6 + 16 * i:22 + 16 * i]
        hx, hy = struct.unpack("<HH", entry[4:8])
        size, offset = struct.unpack("<II", entry[8:16])
        blob = data[offset:offset + size]
        header = struct.unpack("<IiiHHIIiiII", blob[:40])
        w, h = header[1], header[2] // 2
        px = np.frombuffer(blob[40:40 + w * h * 4], dtype=np.uint8)
        px = px.reshape(h, w, 4)[::-1]
        out.append((Image.fromarray(px[:, :, [2, 1, 0, 3]].copy(), "RGBA"), (hx, hy)))
    return out


def recolor_cur(src, dst, brand):
    """Repaint a template cursor in the artwork's colour.

    Only the hue moves: the template's own shading — white rim, deep outline,
    highlight — keeps its value, so the glyphs stay as legible as they were
    while matching the portraits beside them.
    """
    hue, sat, _v = rgb_to_hsv(brand[0] / 255.0, brand[1] / 255.0, brand[2] / 255.0)
    scale = max(0.55, min(1.45, sat / 0.55))
    items = []
    for img, hotspot in read_cur_images(src):
        source = np.array(img)
        hsv = np.array(img.convert("HSV"), dtype=np.float32)
        s = hsv[:, :, 1]
        tinted = s > 18
        hsv[:, :, 0][tinted] = hue * 255.0
        hsv[:, :, 1][tinted] = np.clip(s[tinted] * scale, 0, 255)
        out = np.array(Image.fromarray(np.uint8(np.clip(hsv, 0, 255)), "HSV").convert("RGBA"))
        # HSV has no alpha channel: without this the whole glyph sits on a
        # black square.
        out[:, :, 3] = source[:, :, 3]
        items.append((Image.fromarray(out, "RGBA"), hotspot))
    write_cur(dst, items)


def write_cur(path, items):
    head = struct.pack("<HHH", 0, 2, len(items))
    entries, blobs = b"", []
    offset = 6 + 16 * len(items)
    for img, (hx, hy) in items:
        entry, data = to_cur_image(img, hx, hy)
        entry = entry[:12] + struct.pack("<I", offset) + entry[16:]
        entries += entry
        blobs.append(data)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(head + entries + b"".join(blobs))


def chunk(tag, payload):
    out = tag + struct.pack("<I", len(payload)) + payload
    return out + (b"\x00" if len(payload) & 1 else b"")


def write_ani(path, frames, rates=None):
    """RIFF/ACON. cSteps must equal cFrames or Windows rejects the file."""
    tmp = os.path.join(os.path.dirname(path), "_frame.tmp.cur")
    blobs = []
    for items in frames:
        write_cur(tmp, items)
        with open(tmp, "rb") as f:
            blobs.append(f.read())
    os.remove(tmp)
    n = len(blobs)
    rates = rates or [5] * n
    anih = struct.pack("<IIIIIIIII", 36, n, n, 0, 0, 32, 1,
                       int(round(sum(rates) / float(n))), 1)
    fram = b"".join(chunk(b"icon", b) for b in blobs)
    list_fram = b"LIST" + struct.pack("<I", 4 + len(fram)) + b"fram" + fram
    body = chunk(b"anih", anih) + chunk(b"rate", struct.pack("<%dI" % n, *rates)) + list_fram
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"ACON" + body)


def hs(key, size):
    hx, hy = HOTSPOT[key]
    k = size / 32.0
    return (int(round(hx * k)), int(round(hy * k)))


# ------------------------------------------------------------------- artwork ---
def cutout(path, thresh=26):
    """Return RGBA artwork. Keeps real alpha, otherwise floods the corners."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        a = np.array(im.getchannel("A"))
        if float((a < 250).mean()) > 0.12:
            return im
    rgb = im.convert("RGB")
    if max(rgb.size) > 1400:
        rgb.thumbnail((1400, 1400), Image.LANCZOS)
    work = rgb.copy()
    w, h = work.size
    key = (255, 0, 255)
    # Illustrations arrive on white paper or on a black backdrop; a threshold
    # tuned for one leaves the other almost untouched, so the border decides.
    lum = np.array(rgb).astype(np.float32)
    lum = lum[:, :, 0] * 0.299 + lum[:, :, 1] * 0.587 + lum[:, :, 2] * 0.114
    border = np.concatenate([lum[0, :], lum[-1, :], lum[:, 0], lum[:, -1]])
    if float(np.median(border)) < 96.0:
        # A dark backdrop is rarely one flat colour: glow and vignetting split it
        # into several regions, so seed the whole border instead of four corners.
        gate = float(np.median(border)) + 70.0
        step = max(1, min(w, h) // 24)
        seeds = []
        for x in list(range(0, w, step)) + [w - 1]:
            if lum[0, x] < gate:
                seeds.append((x, 0))
            if lum[h - 1, x] < gate:
                seeds.append((x, h - 1))
        for y in list(range(0, h, step)) + [h - 1]:
            if lum[y, 0] < gate:
                seeds.append((0, y))
            if lum[y, w - 1] < gate:
                seeds.append((w - 1, y))
        for seed in seeds:
            try:
                ImageDraw.floodfill(work, seed, key, thresh=45)
            except Exception:
                pass
    else:
        for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            try:
                ImageDraw.floodfill(work, seed, key, thresh=thresh)
            except Exception:
                pass
    a = np.array(work)
    bg = (a[:, :, 0] == 255) & (a[:, :, 1] == 0) & (a[:, :, 2] == 255)
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([np.array(rgb), alpha]), "RGBA")


def trim(im):
    a = np.array(im.getchannel("A"))
    ys, xs = np.nonzero(a > 8)
    if len(xs) == 0:
        return im
    return im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def top_square(im):
    """The square at the top of the artwork: a portrait's face lives here."""
    w, h = im.size
    side = min(w, h)
    x0 = max(0, (w - side) // 2)
    return im.crop((x0, 0, x0 + side, side))


def coverage(im):
    """Fraction of the frame the cut-out kept."""
    a = np.array(im.getchannel("A"))
    return float((a > 8).mean()) if a.size else 0.0


def focus_square(im, frac=0.62):
    """Square crop around the most colourful part of a close-up portrait.

    A face filling the frame has no separable background, and the whole face is
    unreadable at 32 px. The eyes are the one strongly coloured area, so the
    median of the saturated pixels lands on them and the crop keeps them large.
    """
    w, h = im.size
    side = max(8, int(round(min(w, h) * frac)))
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0.0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    ys, xs = np.nonzero((sat > 0.35) & (mx > 0.25))
    if len(xs) < 50:
        cx, cy = w / 2.0, h * 0.42
    else:
        # The strongest colours — eyes, hair lights — mark the face; a plain
        # median over every tinted pixel drifts into whichever side has more
        # coloured hair.
        strong = sat >= float(np.quantile(sat, 0.97))
        ys, xs = np.nonzero(strong & (mx > 0.25))
        if len(xs) < 50:
            cx, cy = w / 2.0, h * 0.42
        else:
            cx, cy = float(xs.mean()), float(ys.mean())
    x0 = int(round(min(max(cx - side / 2.0, 0), w - side)))
    y0 = int(round(min(max(cy - side / 2.0, 0), h - side)))
    return im.crop((x0, y0, x0 + side, y0 + side))


def inset(im, frac):
    w, h = im.size
    dx, dy = int(w * frac), int(h * frac)
    return im.crop((dx, dy, w - dx, h - dy))


def paste_photo(c, photo, box, white=1.15, navy=0.72, clip_circle=None):
    """Place a raster cut-out (aspect preserved, top-left aligned) with a rim."""
    px0, py0 = c.T((box[0], box[1]))
    avail_w = (box[2] - box[0]) * c.k * SS
    avail_h = (box[3] - box[1]) * c.k * SS
    sw, sh = photo.size
    r = min(avail_w / sw, avail_h / sh)
    w, h = max(1, int(round(sw * r))), max(1, int(round(sh * r)))
    im = photo.resize((w, h), Image.LANCZOS)

    layer = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
    px0i, py0i = int(round(px0)), int(round(py0))
    layer.paste(im, (px0i, py0i))
    a = layer.getchannel("A")
    if clip_circle is not None:
        cm = c.ell_mask(clip_circle[0], clip_circle[1], clip_circle[2], clip_circle[3])
        layer.putalpha(Image.fromarray(np.minimum(np.array(a), np.array(cm))))
    else:
        # A close-up portrait has no separable background, so the cut-out keeps
        # the whole frame; a bare square then reads as a pasted photo at 32 px.
        # Round the corners so the artwork owns a tile instead of a photo.
        patch = np.array(a)[py0i:py0i + h, px0i:px0i + w]
        if patch.size and float((patch > 8).mean()) > 0.82:
            rm = Image.new("L", c.img.size, 0)
            rad = int(round(min(w, h) * 0.20))
            ImageDraw.Draw(rm).rounded_rectangle(
                [px0i, py0i, px0i + w - 1, py0i + h - 1], radius=rad, fill=255)
            layer.putalpha(Image.fromarray(np.minimum(np.array(a), np.array(rm))))
    a = layer.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    if navy > 0:
        c.img.paste(Image.new("RGBA", c.img.size, NAVY), (0, 0),
                    dilate(a, c.tw(white + navy)))
    if white > 0:
        c.img.paste(Image.new("RGBA", c.img.size, WHITE), (0, 0), dilate(a, c.tw(white)))
    c.img.alpha_composite(layer)


def art_arrow_photo(c, face):
    """A round portrait with the pointer laid over its corner.

    A square tile reads as a framed photograph lying on the desktop, which is
    exactly what a cursor should not look like; the circle keeps the artwork
    large while dropping the frame.
    """
    cx, cy, R = 15.7, 15.9, 12.4
    c.paint_mask(c.ell_mask(cx, cy, R + 0.95, R + 0.95), WHITE, white=0.95, navy=0.60)
    paste_photo(c, face, (cx - R, cy - R, cx + R, cy + R), white=0.0, navy=0.0,
                clip_circle=(cx, cy, R, R))
    c.paint_poly(arrow_pts(s=0.62, org=(1.5, 1.4)),
                 BRAND_D, white=0.88, navy=0.54)


def art_help_photo(c, face):
    c.paint_poly(arrow_pts(s=0.80, org=(1.9, 1.9)),
                 BRAND_D, white=1.0, navy=0.62)
    bx, by, br = 22.4, 22.4, 6.6
    c.paint_mask(c.ell_mask(bx, by, br, br), WHITE, white=1.0, navy=0.62)
    paste_photo(c, face, (bx - br + 0.8, by - br + 0.8, bx + br - 0.8, by + br - 0.8),
                white=0.0, navy=0.0, clip_circle=(bx, by, br - 0.78, br - 0.78))


def art_busy_photo(c, face, phase, n=10):
    R = 11.3
    c.paint_mask(c.ell_mask(16, 16, R + 0.85, R + 0.85), WHITE, white=0.95, navy=0.58)
    paste_photo(c, face, (16 - R, 16 - R, 16 + R, 16 + R), white=0.0, navy=0.0,
                clip_circle=(16, 16, R, R))
    # The spin ring goes last: painted underneath the face ring its inner half
    # was swallowed by that ring's halo and the cursor stopped looking animated.
    m = arc_mask(c, 16, 16, 13.4, 1.7, phase, n, span=0.72)
    c.paint_mask(m, c.grad(BRAND_L, BRAND, 0.5), white=0.90, navy=0.62)


def art_app_photo(c, face, phase, n=8):
    c.paint_poly(arrow_pts(s=0.53, org=(2.4, 2.2)),
                 BRAND_D, white=0.90, navy=0.55)
    cx = cy = 20.9
    Rr = 8.2
    R = 6.4
    c.paint_mask(c.ell_mask(cx, cy, R + 0.75, R + 0.75), WHITE, white=0.90, navy=0.55)
    paste_photo(c, face, (cx - R, cy - R, cx + R, cy + R), white=0.0, navy=0.0,
                clip_circle=(cx, cy, R, R))
    # Ring on top, for the same reason as the busy cursor.
    m = arc_mask(c, cx, cy, Rr, 1.5, phase, n, span=0.55, ccw=True)
    c.paint_mask(m, c.grad(BRAND_L, BRAND, 0.4), white=0.85, navy=0.58)


# ------------------------------------------------------------------- palette ---
def hex_rgb(value):
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255)


def palette_from(seed):
    """Derive the accent trio from one base colour."""
    r, g, b = seed[:3]
    br = (int(r), int(g), int(b), 255)
    light = (min(255, int(r + (255 - r) * 0.52)),
             min(255, int(g + (255 - g) * 0.52)),
             min(255, int(b + (255 - b) * 0.52)), 255)
    # A deep tone of the *same* hue: the glyph has to stay readable on top of
    # artwork carrying that very tint, and a fixed indigo would repaint every
    # picture the same colour.
    h, s, _v = rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    dark = hsv_to_rgb(h, max(0.42, min(1.0, s * 1.15)), 0.30)
    return br, light, (dark[0], dark[1], dark[2], 255)


def rgb_to_hsv(r, g, b):
    """RGB in 0..1 to HSV."""
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d <= 1e-6:
        return 0.0, 0.0, mx
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = ((b - r) / d) + 2.0
    else:
        h = ((r - g) / d) + 4.0
    return h / 6.0, d / mx, mx


def hsv_to_rgb(h, s, v):
    """HSV in 0..1 to an RGB tuple of ints."""
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def sample_accent(art):
    """Mix the picture's colours in proportion to the area they cover.

    A single dominant hue goes wrong whenever a warm key light outweighs the
    character's own palette: the cursor then wears a colour the picture never
    actually reads as. Averaging every pixel keeps that balance — but the raw
    average of an artwork is a pale wash, so the mix is pushed to a mid tone
    that can survive as a one-pixel ring.
    """
    small = art.convert("RGBA").resize((160, 160), Image.LANCZOS)
    a = np.array(small, dtype=np.float32)
    rgb = a[:, :, :3].reshape(-1, 3) / 255.0
    alpha = a[:, :, 3].reshape(-1)
    rgb = rgb[alpha > 200]
    if len(rgb) < 50:
        return None
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    lo, hi = np.quantile(lum, [0.10, 0.90])
    # Trim the extremes: a black backdrop or a white bloom would otherwise set
    # the average on its own.
    mid = rgb[(lum >= lo) & (lum <= hi)]
    if len(mid) < 40:
        mid = rgb
    return tuple(int(round(v * 255)) for v in at_value(saturate(mid.mean(0), 0.46), 0.78))


def at_value(rgb, target):
    """Scale a colour to a fixed HSV value, keeping its hue and saturation."""
    v = float(rgb.max())
    if v <= 0.02:
        return rgb
    return np.clip(rgb * (target / v), 0.0, 1.0)


def saturate(rgb, floor):
    """Push a dull blend out to `floor` saturation, keeping its hue."""
    mx, mn = float(rgb.max()), float(rgb.min())
    if mx <= 0.02:
        return rgb
    sat = (mx - mn) / max(mx, 1e-6)
    if sat >= floor:
        return rgb
    grey = float(rgb.mean())
    out = grey + (rgb - grey) * (floor / max(sat, 1e-6))
    return np.clip(out, 0.0, 1.0)


def hue_of(rgb):
    """Hue in turns, for an Nx3 float array in 0..1."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    mx, mn = rgb.max(1), rgb.min(1)
    d = np.maximum(mx - mn, 1e-6)
    h = np.zeros_like(mx)
    m = mx == r
    h[m] = ((g - b)[m] / d[m]) % 6.0
    m = mx == g
    h[m] = ((b - r)[m] / d[m]) + 2.0
    m = mx == b
    h[m] = ((r - g)[m] / d[m]) + 4.0
    return h / 6.0


# ------------------------------------------------------------------- preview ---
def build_preview(path, arrow_img, busy_frames, app_frames):
    W, H = 780, 356
    sheet = Image.new("RGB", (W, H), (247, 248, 252))
    d = ImageDraw.Draw(sheet)

    def label(xy, text):
        d.text(xy, text, fill=(70, 76, 96))

    zoom = lambda im: im.resize((96, 96), Image.LANCZOS)

    label((24, 16), "arrow")
    sheet.paste(zoom(arrow_img), (24, 40), zoom(arrow_img))

    label((166, 16), "busy  (10 frames)")
    for i, f in enumerate(busy_frames):
        z = zoom(f)
        sheet.paste(z, (166 + i * 148, 40), z)

    label((24, 186), "appstarting  (8 frames)")
    for i, f in enumerate(app_frames):
        z = zoom(f)
        sheet.paste(z, (24 + i * 148, 210), z)

    label((610, 186), "hotspot follows")
    label((610, 204), "the artwork,")
    label((610, 222), "the accent arrow")
    label((610, 240), "sits on top.")
    sheet.save(path)


# ---------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default="")
    ap.add_argument("--accent", default="")
    ap.add_argument("--label", default="Picture")
    args = ap.parse_args()

    global BRAND, BRAND_L, BRAND_D

    art = cutout(args.image)
    full = trim(art)
    if full.size[0] < 8 or full.size[1] < 8:
        raise SystemExit("artwork is empty after background removal")
    if coverage(art) > 0.80:
        # A close-up portrait has no separable background, so the frame *is* the
        # subject; cropping into the eyes is what stays readable at 32 px.
        head = focus_square(full, 0.86)
        # Losing resolution costs separation: a pale portrait smears into the
        # background at 32 px unless the colour and contrast are pushed back.
        head = ImageEnhance.Color(ImageEnhance.Contrast(head).enhance(1.12)).enhance(1.22)
        face = head
    else:
        head = trim(top_square(full)) or full
        face = trim(inset(head, 0.14)) or head

    seed = hex_rgb(args.accent) if args.accent else sample_accent(full)
    if seed is None:
        seed = (77, 107, 254)
    BRAND, BRAND_L, BRAND_D = palette_from(seed)

    out = args.out
    if not os.path.isdir(out):
        os.makedirs(out)

    sizes = SIZES
    meta = {
        "label": args.label,
        "source": os.path.abspath(args.image),
        "artwork": list(full.size),
        "head": list(head.size),
        "face": list(face.size),
        "accent": "#%02x%02x%02x" % (BRAND[0], BRAND[1], BRAND[2]),
        "roles": [],
    }

    items = []
    for s in sizes:
        c = Canvas(s)
        art_arrow_photo(c, face)
        items.append((c.out(), hs("arrow", s)))
    write_cur(os.path.join(out, "arrow.cur"), items)
    meta["roles"].append("arrow.cur")

    items = []
    for s in sizes:
        c = Canvas(s)
        art_help_photo(c, face)
        items.append((c.out(), hs("help", s)))
    write_cur(os.path.join(out, "help.cur"), items)
    meta["roles"].append("help.cur")

    busy_frames = []
    for ph in range(10):
        fr = []
        for s in sizes:
            c = Canvas(s)
            art_busy_photo(c, face, ph, 10)
            fr.append((c.out(), hs("busy", s)))
        busy_frames.append(fr)
    write_ani(os.path.join(out, "busy.ani"), busy_frames, rates=[5] * 10)
    meta["roles"].append("busy.ani")

    app_frames = []
    for ph in range(8):
        fr = []
        for s in sizes:
            c = Canvas(s)
            art_app_photo(c, face, ph, 8)
            fr.append((c.out(), hs("appstarting", s)))
        app_frames.append(fr)
    write_ani(os.path.join(out, "appstarting.ani"), app_frames, rates=[6] * 8)
    meta["roles"].append("appstarting.ani")

    # The twelve glyph roles come straight from the bundled template, wearing
    # the artwork's own colour so the set does not read as two families.
    missing = []
    if args.template and os.path.isdir(args.template):
        for name in TEMPLATE_ROLES:
            src = os.path.join(args.template, name)
            if os.path.exists(src):
                recolor_cur(src, os.path.join(out, name), BRAND)
                meta["roles"].append(name)
            else:
                missing.append(name)
    else:
        missing = list(TEMPLATE_ROLES)
        raise SystemExit("template folder is missing: %r" % (args.template,))
    meta["missing"] = missing

    build_preview(os.path.join(out, "preview.png"),
                  arrow_items_64(out),
                  [f[2][0] for f in busy_frames[:4]],
                  [f[2][0] for f in app_frames[:4]])

    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(json.dumps({"ok": True, "out": out, "roles": len(meta["roles"]),
                      "accent": meta["accent"], "missing": missing}))


def arrow_items_64(out):
    """Re-open the finished arrow so the preview matches what got written."""
    path = os.path.join(out, "arrow.cur")
    with open(path, "rb") as f:
        data = f.read()
    count = struct.unpack("<H", data[4:6])[0]
    best = None
    for i in range(count):
        e = data[6 + 16 * i: 22 + 16 * i]
        w = e[0] or 256
        size, off = struct.unpack("<II", e[8:16])
        if best is None or w > best[0]:
            best = (w, size, off)
    _, size, off = best
    blob = data[off: off + size]
    hdr = struct.unpack("<IiiHHIIiiII", blob[:40])
    w, h = hdr[1], hdr[2] // 2
    px = blob[40: 40 + w * h * 4]
    arr = np.frombuffer(px, dtype=np.uint8).reshape(h, w, 4)[::-1]
    return Image.fromarray(np.dstack([arr[:, :, 2], arr[:, :, 1], arr[:, :, 0], arr[:, :, 3]]), "RGBA")


if __name__ == "__main__":
    main()