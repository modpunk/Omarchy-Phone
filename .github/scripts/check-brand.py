#!/usr/bin/env python3
"""Validate brand/ SVGs are well-formed, and brand/png/* both match the sizes
their filenames promise and the aspect ratio of the source SVG they were
rendered from (see brand/tools/render.sh for the filename -> source mapping).

No PyPI dependencies: XML parsing via the stdlib, PNG dimensions read
straight out of the IHDR chunk.
"""
import glob
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

ok = True


def fail(msg):
    global ok
    print("FAIL: " + msg)
    ok = False


def check_svgs():
    svgs = sorted(glob.glob("brand/**/*.svg", recursive=True))
    if not svgs:
        print("no SVGs under brand/ yet, skipping")
        return
    for path in svgs:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            fail(f"{path}: not well-formed XML ({e})")
            continue
        tag = root.tag.rsplit("}", 1)[-1]
        if tag != "svg":
            fail(f"{path}: root element is <{tag}>, not <svg>")
        else:
            print(f"ok: {path}")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def expected_from_name(name):
    # icon-<N>.png -> N x N
    m = re.fullmatch(r"icon-(\d+)\.png", name)
    if m:
        n = int(m.group(1))
        return n, n
    # <anything>-<W>x<H>.png -> W x H
    m = re.fullmatch(r".+-(\d+)x(\d+)\.png", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    # <anything>-<W>.png -> width W, any height (e.g. logo-dark-1600.png)
    m = re.fullmatch(r".+-(\d+)\.png", name)
    if m:
        return int(m.group(1)), None
    return None


def source_svg_for(name):
    """Which brand/*.svg render.sh rasterises this PNG from, if any."""
    stem = name[:-4]
    if re.fullmatch(r"icon-\d+", stem):
        base = "mark-dark"
    else:
        m = re.fullmatch(r"(.+)-\d+x\d+", stem) or re.fullmatch(r"(.+)-\d+", stem)
        base = m.group(1) if m else None
    if base is None:
        return None
    path = f"brand/{base}.svg"
    return path if os.path.exists(path) else None


def svg_viewbox(path):
    root = ET.parse(path).getroot()
    vb = root.get("viewBox")
    if vb:
        parts = vb.split()
        if len(parts) == 4:
            return float(parts[2]), float(parts[3])
    w, h = root.get("width"), root.get("height")
    if w and h:
        return float(re.sub(r"[^0-9.]", "", w)), float(re.sub(r"[^0-9.]", "", h))
    return None


def check_pngs():
    pngs = sorted(glob.glob("brand/png/*.png"))
    if not pngs:
        print("no PNGs under brand/png/ yet, skipping")
        return
    for path in pngs:
        name = path.rsplit("/", 1)[-1]
        size = png_size(path)
        if size is None:
            fail(f"{path}: not a valid PNG (bad signature)")
            continue
        w, h = size

        exp = expected_from_name(name)
        if exp is None:
            print(f"skip (no naming convention matched): {path} is {w}x{h}")
            continue
        ew, eh = exp
        if w != ew or (eh is not None and h != eh):
            fail(f"{path}: is {w}x{h}, filename promises {ew}x{eh if eh is not None else '*'}")
            continue

        src = source_svg_for(name)
        if src is None:
            print(f"ok: {path} is {w}x{h} (no source SVG found to cross-check aspect ratio)")
            continue
        vb = svg_viewbox(src)
        if vb is None:
            print(f"ok: {path} is {w}x{h} ({src} has no viewBox/width+height to compare against)")
            continue
        vb_w, vb_h = vb
        # height implied by the PNG's own width and the source's aspect ratio,
        # allowing +-1px for rsvg-convert's own rounding.
        implied_h = round(w * vb_h / vb_w)
        if abs(implied_h - h) > 1:
            fail(f"{path}: is {w}x{h}, but {src} (viewBox {vb_w:g}x{vb_h:g}) implies ~{w}x{implied_h}")
        else:
            print(f"ok: {path} is {w}x{h}, matches {src}'s aspect ratio")


check_svgs()
check_pngs()
sys.exit(0 if ok else 1)
