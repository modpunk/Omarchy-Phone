#!/usr/bin/env python3
"""Validate brand/ SVGs are well-formed and brand/png/* match the sizes their
filenames promise (see brand/tools/render.sh for the naming convention).

No PyPI dependencies: XML parsing via the stdlib, PNG dimensions read
straight out of the IHDR chunk.
"""
import glob
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
        exp = expected_from_name(name)
        if exp is None:
            print(f"skip (no naming convention matched): {path} is {size[0]}x{size[1]}")
            continue
        ew, eh = exp
        w, h = size
        if w != ew or (eh is not None and h != eh):
            fail(f"{path}: is {w}x{h}, filename promises {ew}x{eh if eh is not None else '*'}")
        else:
            print(f"ok: {path} is {w}x{h}")


check_svgs()
check_pngs()
sys.exit(0 if ok else 1)
