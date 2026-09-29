#!/usr/bin/env python3
"""Generate the Omarchy Phone brand SVGs from pixel bitmaps.

Everything in the mark and the wordmark is drawn on a square pixel grid, the
way the Omarchy logo and icon are. Each bitmap is traced into one clean outline
path (no overlapping rectangles, so no hairline seams when scaled).

The motto is set in Cinzel (SIL OFL 1.1) and converted to outlines, so the
SVGs never depend on a font being installed. That step needs fontTools:

    python3 -m venv /tmp/venv && /tmp/venv/bin/pip install fonttools
    CINZEL_TTF=/path/to/Cinzel[wght].ttf /tmp/venv/bin/python brand/tools/build.py

Cinzel: https://github.com/google/fonts/tree/main/ofl/cinzel
"""
import os
import sys

BRAND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- palette
# Omarchy's icon green is Tokyo Night `green`; Tokyo Night is Omarchy's
# default theme. Light-background colours come from Tokyo Night Day.
DARK = dict(ink="#c0caf5", green="#9ece6a", motto="#a9b1d6", bg="#1a1b26")
LIGHT = dict(ink="#1a1b26", green="#587539", motto="#414868", bg="#ffffff")

# ---------------------------------------------------------------- tracer
def trace(cells):
    """Outline the union of unit cells as closed loops (clockwise on screen)."""
    edges = {}
    for (x, y) in cells:
        if (x, y - 1) not in cells: edges.setdefault((x, y), []).append((x + 1, y))
        if (x + 1, y) not in cells: edges.setdefault((x + 1, y), []).append((x + 1, y + 1))
        if (x, y + 1) not in cells: edges.setdefault((x + 1, y + 1), []).append((x, y + 1))
        if (x - 1, y) not in cells: edges.setdefault((x, y + 1), []).append((x, y))
    loops = []
    while edges:
        start = min(edges)
        pts, prev, cur = [start], None, start
        while True:
            outs = edges[cur]
            nxt = outs[0]
            if len(outs) > 1 and prev is not None:
                # at a corner-touch keep turning right: diagonal neighbours stay separate
                dx, dy = cur[0] - prev[0], cur[1] - prev[1]
                right = (cur[0] - dy, cur[1] + dx)
                if right in outs:
                    nxt = right
            outs.remove(nxt)
            if not outs:
                del edges[cur]
            prev, cur = cur, nxt
            if cur == start:
                break
            pts.append(cur)
        n = len(pts)
        loops.append([pts[i] for i in range(n)
                      if (pts[i][0] - pts[i - 1][0]) * (pts[(i + 1) % n][1] - pts[i][1])
                      != (pts[i][1] - pts[i - 1][1]) * (pts[(i + 1) % n][0] - pts[i][0])])
    return loops


def num(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def path_d(cells, unit=1, ox=0, oy=0):
    out = []
    for lp in trace(cells):
        x0, y0 = lp[0]
        s, py = "M%s %s" % (num(ox + x0 * unit), num(oy + y0 * unit)), y0
        for (x, y) in lp[1:] + [lp[0]]:
            s += ("H%s" % num(ox + x * unit)) if y == py else ("V%s" % num(oy + y * unit))
            py = y
        out.append(s + "Z")
    return "".join(out)


def bitmap(rows, dx=0, dy=0):
    return {(x + dx, y + dy) for y, r in enumerate(rows) for x, c in enumerate(r) if c == "#"}

# ---------------------------------------------------------------- the mark
# The Omarchy icon (15x15: outer ring, inner ring, a top tab, a left tab, a
# bottom tab and a break in each ring) stood up into a 10x16 handset with its
# corners stepped, plus two stepped sound arcs: the ring opening into a voice.
MARK = [
    ".########.......",
    "#..#.....#......",
    "#.##..##.#...#..",
    "#.#....#.#....#.",
    "#.#....#.#....#.",
    "#.#....#.#.#...#",
    "#.#....#.#..#..#",
    "###....#.#..#..#",
    "#.#....#.#..#..#",
    "#.#....#.#..#..#",
    "#.#....#.#.#...#",
    "#.#....#.#....#.",
    "#.#....#.#....#.",
    "#.######.#...#..",
    "#..#.....#......",
    ".###..###.......",
]

# ---------------------------------------------------------------- wordmark
# OMARCHY: the Omarchy logo.svg letterforms, cell for cell (15 px cells,
# 81x19). Traced from /usr/share/omarchy/logo.svg (MIT, (c) DHH).
OMARCHY = """\
.................###.............................................................
..#####......###########......#######....#######....#######....#...#......#...#..
.#######....#############....########...########...########...##...##....##...##.
###...###..###...###...###..###...###..###...###..###...###..###...###..###...###
###...###..###...###...###..###...###..###...###..###...###..###...###..###...###
###...###..###...###...###..###...###..###...###..###...##...###...###..###...###
###...###..###...###...###..###...###..###...###..###...#....###...###..###...###
###...###..###...###...###..###...###..###...###..###........###...###..###...###
###...###..###...###...###.##########.#########...###.......###########.#########
###...###..###...###...###.##########.########....###......###########..#########
###...###..###...###...###..###...###..###........###........###...###........###
###...###..###...###...###..###...###.##########..###...#....###...###...##...###
###...###..###...###...###..###...###.##########..###...##...###...###..###...###
###...###..###...###...###..###...###..###...###..###...###..###...###..###...###
###...###..###...###...###..###...###..###...###..###...###..###...###..###...###
.#######....##...###...##...###...##...###...###..########...###...##....#######.
..#####......#...###...#....###...#....###...###..#######....###...#......#####..
.......................................###...##..................................
.......................................###...#...................................
""".splitlines()

# PHONE: H and O are Omarchy's own; P is Omarchy's R without its leg, N is
# Omarchy's M with one stem fewer, E is Omarchy's C with R's bowl bar.
# Columns: two spur columns, a 9-wide body, one spur column (12 wide).
PHONE_LETTERS = {
    "P": ["............", "....#######.", "...########.", "..###...###.", "..###...###.",
          "..###...###.", "..###...###.", "..###...###.", ".#########..", ".########...",
          "..###.......", "..###.......", "..###.......", "..###.......", "..###.......",
          "..###.......", "..###.......", "............", "............"],
    "H": ["............", ".....#...#..", "....##...##.", "...###...###", "...###...###",
          "...###...###", "...###...###", "...###...###", "..###########", ".##########.",
          "...###...###", "...###...###", "...###...###", "...###...###", "...###...###",
          "...###...##.", "...###...#..", "............", "............"],
    "O": ["............", "....#####...", "...#######..", "..###...###.", "..###...###.",
          "..###...###.", "..###...###.", "..###...###.", "..###...###.", "..###...###.",
          "..###...###.", "..###...###.", "..###...###.", "..###...###.", "..###...###.",
          "...#######..", "....#####...", "............", "............"],
    "N": ["............", "....#####...", "...#######..", "..###...###.", "..###...###.",
          "..###...###.", "..###...###.", "..###...###.", "..###...###.", "..###...###.",
          "..###...###.", "..###...###.", "..###...###.", "..###...###.", "..###...###.",
          "...##...##..", "....#...#...", "............", "............"],
    "E": ["............", "....#######.", "...########.", "..###...###.", "..###...###.",
          "..###...##..", "..###.......", "..###.......", ".########...", ".#######....",
          "..###.......", "..###.......", "..###...##..", "..###...###.", "..###...###.",
          "..########..", "..#######...", "............", "............"],
}
PITCH = 11          # 9-wide body + 2 cells of air, as in OMARCHY
WORD_GAP = 6        # air between Y and P


def wordmark_cells():
    """-> (omarchy_cells, phone_cells, width_in_cells)"""
    om = bitmap(OMARCHY)
    ph = set()
    body0 = 81 + WORD_GAP
    for i, ch in enumerate("PHONE"):
        ph |= bitmap(PHONE_LETTERS[ch], dx=body0 + i * PITCH - 2)
    width = max(x for x, _ in ph) + 1
    return om, ph, width

# ---------------------------------------------------------------- motto
def motto_paths(text, cap_height, tracking_em, ox=0.0, base=0.0, weight=600):
    """Outline `text` in Cinzel at (ox, baseline). Returns (d, advance_width)."""
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    ttf = os.environ.get("CINZEL_TTF") or os.path.join(BRAND, "fonts", "Cinzel.ttf")
    if not os.path.exists(ttf):
        sys.exit("Cinzel not found: set CINZEL_TTF (see the docstring)")
    font = TTFont(ttf)
    upm = font["head"].unitsPerEm
    s = cap_height / font["OS/2"].sCapHeight
    gs = font.getGlyphSet(location={"wght": weight})
    cmap = font.getBestCmap()
    pen = SVGPathPen(gs, ntos=lambda v: num(round(v, 1)))
    x = 0.0
    for i, ch in enumerate(text):
        g = gs[cmap[ord(ch)]]
        g.draw(TransformPen(pen, (s, 0, 0, -s, ox + x, base)))
        x += g.width * s + (tracking_em * upm * s if i < len(text) - 1 else 0)
    return pen.getCommands(), x


def rect(x0, y0, x1, y1):
    return "M%s %sH%sV%sH%sZ" % (num(x0), num(y0), num(x1), num(y1), num(x0))


def motto_line(cap, tracking, left, right, base, bar, rule_gap, inset):
    """VOX \u00b7 LIBERTATIS centred between left and right on `base`, with a square
    interpunct and flanking rules `bar` thick. -> (text_d, green_d)"""
    em = cap / 0.7                      # Cinzel cap height is 0.7 em
    _, w1 = motto_paths("VOX", cap, tracking)
    _, w2 = motto_paths("LIBERTATIS", cap, tracking)
    gap = 3 * tracking * em + bar
    total = w1 + gap + w2
    tx = (left + right - total) / 2
    d1, _ = motto_paths("VOX", cap, tracking, tx, base)
    d2, _ = motto_paths("LIBERTATIS", cap, tracking, tx + w1 + gap, base)
    mid = base - cap / 2
    dot_x = tx + w1 + gap / 2
    green = (rect(left + inset, mid - bar / 2, tx - rule_gap, mid + bar / 2)
             + rect(dot_x - bar / 2, mid - bar / 2, dot_x + bar / 2, mid + bar / 2)
             + rect(tx + total + rule_gap, mid - bar / 2, right - inset, mid + bar / 2))
    return d1 + d2, green

# ---------------------------------------------------------------- SVG out
def svg(w, h, body, title, style=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s"'
            ' role="img" aria-labelledby="t">\n<title id="t">%s</title>\n%s%s</svg>\n'
            % (num(w), num(h), num(w), num(h), title, style, body))


ADAPTIVE = ("<style>\n.i{fill:%s}.g{fill:%s}.m{fill:%s}\n"
            "@media (prefers-color-scheme:dark){.i{fill:%s}.g{fill:%s}.m{fill:%s}}\n</style>\n"
            % (LIGHT["ink"], LIGHT["green"], LIGHT["motto"], DARK["ink"], DARK["green"], DARK["motto"]))


def paint(pal, cls):
    """fill attribute for a fixed palette, class for the adaptive file"""
    key = {"i": "ink", "g": "green", "m": "motto"}[cls]
    return ('class="%s"' % cls) if pal is None else ('fill="%s"' % pal[key])


def write(name, text):
    with open(os.path.join(BRAND, name), "w") as f:
        f.write(text)
    print("wrote brand/" + name)


U = 15              # wordmark cell, same as Omarchy's logo.svg
MU = 25             # mark cell in the lockup (mark 400 tall beside a 285 wordmark)


def build(pal):
    style = ADAPTIVE if pal is None else ""
    mark = bitmap(MARK)
    om, ph, wcells = wordmark_cells()

    # mark alone: 16x16 cells on a 16x16 viewBox scaled to 512
    mark_svg = svg(512, 512, '<path %s d="%s"/>\n' % (paint(pal, "g"), path_d(mark, 32)),
                   "Omarchy Phone", style)

    # wordmark alone
    ww, wh = wcells * U, 19 * U
    word = ('<path %s d="%s"/>\n<path %s d="%s"/>\n'
            % (paint(pal, "i"), path_d(om, U), paint(pal, "g"), path_d(ph, U)))
    word_svg = svg(ww, wh, word, "Omarchy Phone", style)

    # lockup: mark | wordmark over motto. The wordmark body (rows 1-16) spans
    # the mark's top; the motto's baseline sits on the mark's foot.
    mh = 16 * MU                       # 400
    gap = 6 * U                        # 90
    x0 = 16 * MU + gap
    my = U                             # the M's ascender (row 0) rises above the mark
    base = my + mh
    td, gd = motto_line(84, 0.30, x0, x0 + ww, base, U, 2 * U, 3 * U)
    lock = ('<path %s d="%s"/>\n' % (paint(pal, "g"), path_d(mark, MU, 0, my))
            + '<path %s d="%s"/>\n' % (paint(pal, "i"), path_d(om, U, x0))
            + '<path %s d="%s"/>\n' % (paint(pal, "g"), path_d(ph, U, x0) + gd)
            + '<path %s d="%s"/>\n' % (paint(pal, "m"), td))
    lock_svg = svg(x0 + ww, base, lock, "Omarchy Phone — Vox Libertatis", style)
    return mark_svg, word_svg, lock_svg


def social():
    """1280x640 GitHub social preview, stacked lockup on Tokyo Night background."""
    pal = DARK
    mark = bitmap(MARK)
    om, ph, wcells = wordmark_cells()
    W, H = 1280, 640
    mcell = 14                                   # mark 224 px
    mx, my = (W - 16 * mcell) / 2, 72
    u = 7.5                                      # wordmark cell -> 1050 px wide
    wx, wy = (W - wcells * u) / 2, my + 16 * mcell + 44
    cap = 34
    base = wy + 17 * u + 34 + cap
    td, gd = motto_line(cap, 0.32, wx, wx + wcells * u, base, u, 24, 0)
    body = ('<rect width="%d" height="%d" fill="%s"/>\n' % (W, H, pal["bg"])
            + '<path fill="%s" d="%s"/>\n' % (pal["green"], path_d(mark, mcell, mx, my))
            + '<path fill="%s" d="%s"/>\n' % (pal["ink"], path_d(om, u, wx, wy))
            + '<path fill="%s" d="%s"/>\n' % (pal["green"], path_d(ph, u, wx, wy) + gd)
            + '<path fill="%s" d="%s"/>\n' % (pal["motto"], td))
    return svg(W, H, body, "Omarchy Phone — Vox Libertatis")


def main():
    for suffix, pal in (("", None), ("-light", LIGHT), ("-dark", DARK)):
        m, w, l = build(pal)
        write("mark%s.svg" % suffix, m)
        write("wordmark%s.svg" % suffix, w)
        write("logo%s.svg" % suffix, l)
    write("social-preview.svg", social())


if __name__ == "__main__":
    main()
