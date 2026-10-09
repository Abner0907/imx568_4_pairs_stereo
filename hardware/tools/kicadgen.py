"""
Small KiCad 8 board generator used by gen_camera_head.py and gen_stereo_board.py.

Board-relative coordinates in mm, KiCad convention (+X right, +Y down); the
board centre is placed at page (100, 100). Supports:
  * IMX568 instances (footprint with nets, dog-bone fan-out, datasheet
    decoupling on the back, per-sensor net prefixes)
  * CSI-2 pair routing helpers, vias, tracks, zones, holes, keep-out blocks
  * generic chip passives, BGA and FPC footprints
  * a mini-DRC (clearance between different nets on F.Cu / B.Cu / vias)
  * a matplotlib preview
"""
import json
import math
import os
import uuid

from imx568_data import (PINS, CORNER_PADS, DECOUPLING, FILTERS, PKG_W, PKG_H,
                         ball_xy, pin_net)

PAD_D = 0.60          # LGA land phi0.6 (+0.14/-0)
PAD_MASK = 0.05
PAD_PASTE_D = 0.50
CORNER = 1.60
VIA_D, VIA_DRILL = 0.40, 0.20
PX, PY = 100.0, 100.0  # page position of the board centre

_ns = uuid.UUID("6f1d3a52-5b8e-4f0e-9a51-1d6b0c568568")


def f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


# two-pad chip footprints: (pad pitch, pad w, pad h, body w, body h)
CHIP = {"0201": (0.56, 0.36, 0.40, 0.6, 0.3),
        "0402": (0.96, 0.56, 0.62, 1.0, 0.5),
        "0603": (1.55, 0.80, 0.95, 1.6, 0.8),
        "0805": (1.90, 1.00, 1.25, 2.0, 1.25)}
CAP_SIZE = {"1n": "0201", "0.1u": "0201", "1u": "0402", "4.7u": "0402",
            "10u": "0603", "22u": "0603", "10uH": "0805"}


# ------------------------------------------------------------ geometry / DRC
def _pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _seg_seg(a, b):
    (ax1, ay1, ax2, ay2), (bx1, by1, bx2, by2) = a, b

    def ccw(x1, y1, x2, y2, x3, y3):
        return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    d1 = ccw(bx1, by1, bx2, by2, ax1, ay1)
    d2 = ccw(bx1, by1, bx2, by2, ax2, ay2)
    d3 = ccw(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = ccw(ax1, ay1, ax2, ay2, bx2, by2)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return 0.0
    return min(_pt_seg(ax1, ay1, *b), _pt_seg(ax2, ay2, *b),
               _pt_seg(bx1, by1, *a), _pt_seg(bx2, by2, *a))


def _core(s):
    if s[0] == "c":
        return [(s[1], s[2], s[1], s[2])], s[3], None
    if s[0] == "s":
        return [(s[1], s[2], s[3], s[4])], s[5], None
    _, x, y, hx, hy = s[:5]
    c = [(x - hx, y - hy), (x + hx, y - hy), (x + hx, y + hy), (x - hx, y + hy)]
    return [(*c[i], *c[(i + 1) % 4]) for i in range(4)], 0.0, (x, y, hx, hy)


def shape_dist(a, b):
    """Edge-to-edge distance between circle ('c',x,y,r), capsule ('s',x1,y1,x2,y2,r)
    and rect ('r',x,y,hx,hy)."""
    sa, ra, rta = _core(a)
    sb, rb, rtb = _core(b)
    for rt, segs in ((rta, sb), (rtb, sa)):
        if rt:
            x, y, hx, hy = rt
            for (x1, y1, _, _) in segs:
                if abs(x1 - x) <= hx and abs(y1 - y) <= hy:
                    return 0.0
    return max(0.0, min(_seg_seg(p, q) for p in sa for q in sb) - ra - rb)


def bbox(s):
    if s[0] == "c":
        return (s[1] - s[3], s[2] - s[3], s[1] + s[3], s[2] + s[3])
    if s[0] == "s":
        return (min(s[1], s[3]) - s[5], min(s[2], s[4]) - s[5], max(s[1], s[3]) + s[5], max(s[2], s[4]) + s[5])
    return (s[1] - s[3], s[2] - s[4], s[1] + s[3], s[2] + s[4])


# ================================================================ Board
class Board:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.nets = {"": 0}
        self.items = []
        self.copper = {"F.Cu": [], "B.Cu": []}   # (shape, net, tag) for DRC
        self.vias = []
        self.tracks = []
        self.parts = []          # preview: (ref, side, [(x,y,hx,hy,net)])
        self.blocks = []         # (x, y, w, h, label, side)
        self.keepout = {"top": [], "bottom": []}
        self.holes = []
        self.sensors = []        # (ox, oy, prefix)
        self.cref = 1
        self.uid_n = 0

    # ------------------------------------------------------------ basics
    def uid(self, *key):
        return str(uuid.uuid5(_ns, "/".join(map(str, (self.name,) + key))))

    def net(self, n):
        if n not in self.nets:
            self.nets[n] = len(self.nets)
        return self.nets[n]

    def via(self, x, y, net):
        self.vias.append((x, y, VIA_D, net))
        for l in self.copper:
            self.copper[l].append((("c", x, y, VIA_D / 2), net, f"via({x:.2f},{y:.2f})"))
        self.items.append(f'  (via (at {f(PX + x)} {f(PY + y)}) (size {VIA_D}) (drill {VIA_DRILL}) (layers "F.Cu" "B.Cu")'
                          f' (net {self.net(net)}) (uuid "{self.uid("via", x, y)}"))\n')

    def seg(self, x1, y1, x2, y2, w, layer, net):
        self.tracks.append((x1, y1, x2, y2, w, layer, net))
        if layer in self.copper:
            self.copper[layer].append((("s", x1, y1, x2, y2, w / 2), net, f"trk({x1:.2f},{y1:.2f})"))
        self.items.append(f'  (segment (start {f(PX + x1)} {f(PY + y1)}) (end {f(PX + x2)} {f(PY + y2)}) (width {w})'
                          f' (layer "{layer}") (net {self.net(net)}) (uuid "{self.uid("seg", x1, y1, x2, y2, layer)}"))\n')

    def path(self, pts, w, layer, net):
        for (a, b) in zip(pts, pts[1:]):
            self.seg(a[0], a[1], b[0], b[1], w, layer, net)

    def block(self, x, y, w, h, label, side="bottom"):
        self.blocks.append((x, y, w, h, label, side))
        self.keepout[side].append((x, y, w, h))

    def hole(self, x, y, d=2.2):
        i = len(self.holes)
        self.holes.append((x, y, d))
        self.keepout["bottom"].append((x, y, d + 1.0, d + 1.0))
        self.keepout["top"].append((x, y, d + 1.0, d + 1.0))
        self.items.append(f'  (footprint "MountingHole:MountingHole_2.2mm_M2" (layer "F.Cu") (uuid "{self.uid("h", i)}") (at {f(PX + x)} {f(PY + y)})\n'
                          f'    (property "Reference" "H{i + 1}" (at 0 -2 0) (layer "F.SilkS") (uuid "{self.uid("h", i, "r")}") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
                          f'    (property "Value" "M2" (at 0 2 0) (layer "F.Fab") (uuid "{self.uid("h", i, "v")}") (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
                          f'    (attr exclude_from_pos_files exclude_from_bom)\n'
                          f'    (pad "" np_thru_hole circle (at 0 0) (size {d} {d}) (drill {d}) (layers "*.Cu" "*.Mask") (uuid "{self.uid("h", i, "p")}"))\n  )\n')

    def text(self, s, x, y, layer="Cmts.User", size=0.8):
        mir = " (justify mirror)" if layer.startswith("B.") else ""
        self.items.append(f'  (gr_text "{s}" (at {f(PX + x)} {f(PY + y)}) (layer "{layer}") (uuid "{self.uid("txt", s, x, y)}")'
                          f' (effects (font (size {size} {size}) (thickness {round(size * 0.15, 3)})){mir}))\n')

    def rect(self, x1, y1, x2, y2, layer, dash=False, w=0.1):
        self.items.append(f'  (gr_rect (start {f(PX + x1)} {f(PY + y1)}) (end {f(PX + x2)} {f(PY + y2)})'
                          f' (stroke (width {w}) (type {"dash" if dash else "default"})) (fill none) (layer "{layer}")'
                          f' (uuid "{self.uid("rect", x1, y1, layer)}"))\n')

    def zone(self, net, layer, prio=0):
        hw, hh = self.w / 2 - 0.3, self.h / 2 - 0.3
        self.items.append(f'  (zone (net {self.net(net)}) (net_name "{net}") (layer "{layer}") (uuid "{self.uid("zone", net, layer)}")'
                          f' (hatch edge 0.5) (priority {prio})\n'
                          f'    (connect_pads (clearance 0.12)) (min_thickness 0.12) (filled_areas_thickness no)\n'
                          f'    (fill (thermal_gap 0.25) (thermal_bridge_width 0.25))\n'
                          f'    (polygon (pts (xy {f(PX - hw)} {f(PY - hh)}) (xy {f(PX + hw)} {f(PY - hh)})'
                          f' (xy {f(PX + hw)} {f(PY + hh)}) (xy {f(PX - hw)} {f(PY + hh)}))))\n')

    # ------------------------------------------------------------ chips
    def chip(self, ref, val, size, x, y, rot, side, n1, n2):
        pitch, pw, ph, bw, bh = CHIP[size]
        L = "F" if side == "top" else "B"
        mir = "" if side == "top" else " (justify mirror)"
        s = [f'  (footprint "Passives:C_{size}" (layer "{L}.Cu") (uuid "{self.uid(ref)}") (at {f(PX + x)} {f(PY + y)} {rot})\n',
             f'    (property "Reference" "{ref}" (at 0 {-(bh / 2 + 0.5)} {rot}) (layer "{L}.SilkS") (uuid "{self.uid(ref, "r")}") (hide yes)\n'
             f'      (effects (font (size 0.4 0.4) (thickness 0.08)){mir}))\n',
             f'    (property "Value" "{val}" (at 0 {bh / 2 + 0.5} {rot}) (layer "{L}.Fab") (uuid "{self.uid(ref, "v")}")\n'
             f'      (effects (font (size 0.3 0.3) (thickness 0.05)){mir}))\n',
             '    (attr smd)\n',
             f'    (fp_rect (start {-bw / 2} {-bh / 2}) (end {bw / 2} {bh / 2}) (stroke (width 0.05) (type default)) (fill none) (layer "{L}.Fab") (uuid "{self.uid(ref, "fab")}"))\n']
        pads = []
        for i, (px, n) in enumerate(((-pitch / 2, n1), (pitch / 2, n2)), 1):
            s.append(f'    (pad "{i}" smd roundrect (at {f(px)} 0 {rot}) (size {pw} {ph}) (layers "{L}.Cu" "{L}.Paste" "{L}.Mask")'
                     f' (roundrect_rratio 0.25) (net {self.net(n)} "{n}") (uuid "{self.uid(ref, i)}"))\n')
            if rot == 90:
                pads.append((x, y - px if side == "top" else y + px, ph / 2, pw / 2, n))
            else:
                pads.append((x + px, y, pw / 2, ph / 2, n))
        s.append('  )\n')
        self.items.append("".join(s))
        layer = "F.Cu" if side == "top" else "B.Cu"
        for i, p in enumerate(pads):
            self.copper[layer].append((("r",) + p[:4], p[4], f"{ref}.{i + 1}"))
        self.parts.append((ref, side, pads))
        return pads

    def _clear(self, side, x, y, hx, hy, clr):
        if abs(x) + hx > self.w / 2 - 0.4 or abs(y) + hy > self.h / 2 - 0.4:
            return False
        for kx, ky, kw, kh in self.keepout[side]:
            if abs(kx - x) < kw / 2 + hx and abs(ky - y) < kh / 2 + hy:
                return False
        box = ("r", x, y, hx, hy)
        bb = (x - hx - clr, y - hy - clr, x + hx + clr, y + hy + clr)
        for (s, n, t) in self.copper["F.Cu" if side == "top" else "B.Cu"]:
            b = bbox(s)
            if b[2] < bb[0] or b[0] > bb[2] or b[3] < bb[1] or b[1] > bb[3]:
                continue
            if shape_dist(box, s) < clr:
                return False
        return True

    def place_chip(self, ref, val, near, n1, n2, side="bottom", clr=0.12):
        size = CAP_SIZE[val]
        pitch, pw, ph, bw, bh = CHIP[size]
        for r in range(0, 160):
            rr = r * 0.125
            steps = max(8, int(rr * 16))
            for k in range(steps):
                a = 2 * math.pi * k / steps
                cx = round((near[0] + rr * math.cos(a)) * 8) / 8
                cy = round((near[1] + rr * math.sin(a)) * 8) / 8
                for rot in (0, 90):
                    if rot == 0:
                        p = [(cx - pitch / 2, cy, pw / 2, ph / 2), (cx + pitch / 2, cy, pw / 2, ph / 2)]
                    else:
                        p = [(cx, cy + pitch / 2, ph / 2, pw / 2), (cx, cy - pitch / 2, ph / 2, pw / 2)]
                    if all(self._clear(side, *q, clr) for q in p):
                        return self.chip(ref, val, size, cx, cy, rot, side, n1, n2)
        raise RuntimeError(f"no room for {ref} near {near}")

    def stub_ok(self, x1, y1, x2, y2, w, net, layer="B.Cu", clr=0.1):
        s = ("s", x1, y1, x2, y2, w / 2)
        for (o, n, t) in self.copper[layer]:
            if n != net and shape_dist(s, o) < clr:
                return False
        return True

    def next_ref(self, prefix="C"):
        r = f"{prefix}{self.cref}"
        self.cref += 1
        return r

    # ------------------------------------------------------------ IMX568
    @staticmethod
    def sensor_net(n, prefix):
        if n is None or not prefix:
            return n
        if n.startswith(("CSI_", "SNS_", "VCP")):
            return f"{prefix}_{n}"
        if n in ("+1V1_LIF", "+1V1_PLA"):
            return f"{n}_{prefix}"
        return n

    def imx568(self, ref, ox, oy, prefix=""):
        """Sensor footprint + fan-out + decoupling. Returns CSI breakout info."""
        self.sensors.append((ox, oy, prefix))
        sn = lambda b: self.sensor_net(pin_net(b), prefix)       # noqa: E731
        for b in PINS:
            if sn(b):
                self.net(sn(b))
        # footprint
        fp = [f'  (footprint "IMX568:IMX568_LGA132" (layer "F.Cu") (uuid "{self.uid(ref)}") (at {f(PX + ox)} {f(PY + oy)})\n']
        fp.append(footprint_body(ref, "IMX568-AAMJ-C", lambda b: sn(b), self.nets, indent="    "))
        fp.append('  )\n')
        self.items.insert(0, "".join(fp))
        for b in PINS:
            x, y = ball_xy(b)
            n = sn(b) or f"<nc:{ref}.{b}>"
            shp = (("r", ox + x, oy + y, CORNER / 2, CORNER / 2) if b in CORNER_PADS
                   else ("c", ox + x, oy + y, PAD_D / 2))
            self.copper["F.Cu"].append((shp, n, f"{ref}.{b}"))
        self.keepout["top"].append((ox, oy, PKG_W + 0.4, PKG_H + 0.4))

        # fan-out
        mipi_cols = {"E", "F", "G", "H", "J"}
        fan = {}
        for ball in sorted(PINS):
            n = sn(ball)
            if not n or ball in CORNER_PADS:
                continue
            if ball[0] in mipi_cols and ball[1:] in ("11", "12"):
                continue
            x, y = ball_xy(ball)
            sx = 1 if x >= 0 else -1
            sy = 1 if y > 0 else -1
            w = 0.2 if n.startswith("+") or n == "GND" else 0.12
            cands = [(0.5 * sx, 0.5 * sy), (0.5 * sx, -0.5 * sy), (-0.5 * sx, 0.5 * sy),
                     (-0.5 * sx, -0.5 * sy), (0, 0.95 * sy), (0.95 * sx, 0)]
            ok = False
            for dx, dy in cands:
                vx, vy = ox + x + dx, oy + y + dy
                v = ("c", vx, vy, VIA_D / 2)
                t = ("s", ox + x, oy + y, vx, vy, w / 2)
                ok = True
                for (s, on, tag) in self.copper["F.Cu"]:
                    if on == n and not tag.startswith("via"):
                        continue
                    b = bbox(s)
                    if b[2] < vx - 1.5 or b[0] > vx + 1.5 or b[3] < vy - 1.5 or b[1] > vy + 1.5:
                        continue
                    if shape_dist(v, s) < 0.1 or shape_dist(t, s) < 0.1:
                        ok = False
                        break
                if ok:
                    break
            if not ok:
                mate = [ob for ob in fan if sn(ob) == n and math.dist(ball_xy(ob), (x, y)) <= 1.01]
                if not mate:
                    raise RuntimeError(f"no fan-out for {ref}.{ball}")
                mx, my = ball_xy(mate[0])
                self.seg(ox + x, oy + y, ox + mx, oy + my, w, "F.Cu", n)
                fan[ball] = fan[mate[0]]
                continue
            self.seg(ox + x, oy + y, vx, vy, w, "F.Cu", n)
            self.via(vx, vy, n)
            fan[ball] = (vx, vy)
        for ball in CORNER_PADS:
            x, y = ball_xy(ball)
            sx = 1 if x > 0 else -1
            self.seg(ox + x, oy + y, ox + x + sx * 1.35, oy + y, 0.3, "F.Cu", "GND")
            self.via(ox + x + sx * 1.35, oy + y, "GND")

        # CSI breakout through the lower package edge: tightened 100R pairs
        W, GAP = 0.10, 0.15
        half = (W + GAP) / 2
        pairs = []
        for col, base in (("E", "CSI_D3"), ("F", "CSI_D1"), ("G", "CSI_CLK"), ("H", "CSI_D0"), ("J", "CSI_D2")):
            xp, yp = ball_xy(col + "12")
            xn, yn = ball_xy(col + "11")
            P, N = self.sensor_net(base + "_P", prefix), self.sensor_net(base + "_N", prefix)
            xl = xn + 0.5
            c = (xp + xl) / 2
            y0, y1 = 6.05, 6.45
            self.path([(ox + xp, oy + yp), (ox + xp, oy + y0), (ox + c - half, oy + y1)], W, "F.Cu", P)
            self.path([(ox + xn, oy + yn), (ox + xl, oy + yn + 0.5), (ox + xl, oy + y0), (ox + c + half, oy + y1)], W, "F.Cu", N)
            pairs.append(dict(name=base, P=P, N=N, cx=ox + c, y=oy + y1, half=half, w=W))

        # decoupling on the back
        for e in DECOUPLING:
            ref_ball, caps = e[0], e[2]
            if ref_ball:
                net = sn(ref_ball)
                near = fan.get(ref_ball, (ox + ball_xy(ref_ball)[0], oy + ball_xy(ref_ball)[1]))
            else:
                net = e[3]
                near = {"+3V3A": (ox + 2.0, oy - 7.6), "+2V9": (ox + 6.8, oy), "+1V1": (ox - 6.9, oy)}[net]
            for val in caps:
                pads = self.place_chip(self.next_ref("C"), val, near, net, "GND")
                for (px, py, _, _, pn) in pads:
                    best = None
                    for vx, vy, _, vn in self.vias:
                        if vn == pn:
                            d = math.hypot(vx - px, vy - py)
                            if d <= 0.9 and (best is None or d < best[0]):
                                best = (d, vx, vy)
                    if best and self.stub_ok(px, py, best[1], best[2], 0.15, pn):
                        self.seg(px, py, best[1], best[2], 0.15, "B.Cu", pn)
        for _, val, nin, nout, _ in FILTERS:
            nout = self.sensor_net(nout, prefix)
            self.net(nout)
            near = fan["F10"] if "LIF" in nout else fan["L7"]
            self.place_chip(self.next_ref("L"), val, near, nin, nout)
        return pairs

    # ------------------------------------------------------------ CSI routing
    def route_pairs_to(self, pairs, y_rows, x_end, direction, layer_end_vias=True):
        """Route tightened sensor pairs (vertical, going +y) to horizontal rows
        heading towards `direction` (+1 right / -1 left) and end at x_end
        (per pair) with a via pair + GND return via."""
        order = sorted(pairs, key=lambda p: -p["cx"] * direction)   # first to turn = closest to target
        for i, p in enumerate(order):
            yr = y_rows[i]
            xe = x_end[i]
            for net, dx in ((p["P"], -p["half"]), (p["N"], p["half"])):
                inner = (dx > 0) == (direction > 0)
                yh = yr - p["half"] if inner else yr + p["half"]
                xv = p["cx"] + dx
                d = 0.6
                self.path([(xv, p["y"]), (xv, yh - d), (xv + direction * d, yh), (xe, yh)], p["w"], "F.Cu", net)
                if layer_end_vias:
                    vy = yr - 0.3 if yh < yr else yr + 0.3
                    self.seg(xe, yh, xe + direction * 0.4, vy, p["w"], "F.Cu", net)
                    self.via(xe + direction * 0.4, vy, net)
            if layer_end_vias:
                self.via(xe + direction * 1.0, yr, "GND")

    # ------------------------------------------------------------ output
    def drc(self, clearance=0.1):
        errs = []
        for l, lst in self.copper.items():
            boxes = [bbox(s) for s, _, _ in lst]
            idx = sorted(range(len(lst)), key=lambda i: boxes[i][0])
            for a in range(len(idx)):
                i = idx[a]
                for b in range(a + 1, len(idx)):
                    j = idx[b]
                    if boxes[j][0] > boxes[i][2] + clearance:
                        break
                    if boxes[j][1] > boxes[i][3] + clearance or boxes[j][3] < boxes[i][1] - clearance:
                        continue
                    (sa, na, ta), (sb, nb, tb) = lst[i], lst[j]
                    if na == nb:
                        continue
                    d = shape_dist(sa, sb)
                    if d < clearance - 1e-6:
                        errs.append((l, ta, na, tb, nb, round(d, 3)))
        return errs

    def save(self, path, project_rules=None, title=""):
        hw, hh = self.w / 2, self.h / 2
        self.items.append(f'  (gr_rect (start {f(PX - hw)} {f(PY - hh)}) (end {f(PX + hw)} {f(PY + hh)}) (stroke (width 0.1) (type default))'
                          f' (fill none) (layer "Edge.Cuts") (uuid "{self.uid("edge")}"))\n')
        for (x, y, w, h, label, side) in self.blocks:
            L = "B.Fab" if side == "bottom" else "F.Fab"
            self.rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2, L, dash=True)
            self.text(label.replace("\n", "\\n"), x, y, L, 0.5)
        if title:
            self.text(title, 0, hh + 3)
        layers = """  (layers
    (0 "F.Cu" signal) (1 "In1.Cu" power) (2 "In2.Cu" power) (3 "In3.Cu" signal) (4 "In4.Cu" power) (31 "B.Cu" signal)
    (32 "B.Adhes" user "B.Adhesive") (33 "F.Adhes" user "F.Adhesive") (34 "B.Paste" user) (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen") (37 "F.SilkS" user "F.Silkscreen") (38 "B.Mask" user) (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings") (41 "Cmts.User" user "User.Comments") (42 "Eco1.User" user "User.Eco1")
    (43 "Eco2.User" user "User.Eco2") (44 "Edge.Cuts" user) (45 "Margin" user) (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.CrtYd" user "F.Courtyard") (48 "B.Fab" user) (49 "F.Fab" user)
  )
"""
        head = ('(kicad_pcb (version 20240108) (generator "imx568_gen") (generator_version "8.0")\n'
                '  (general (thickness 1.6) (legacy_teardrops no))\n  (paper "A3")\n' + layers +
                '  (setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no))\n')
        nets = "".join(f'  (net {i} "{n}")\n' for n, i in sorted(self.nets.items(), key=lambda kv: kv[1]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(head + nets + "".join(self.items) + ")\n")
        with open(path.replace(".kicad_pcb", ".kicad_pro"), "w") as fh:
            json.dump(project_rules or default_project(os.path.basename(path)), fh, indent=2)

    def preview(self, path, title):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle, Circle

        hw, hh = self.w / 2, self.h / 2
        scale = max(self.w, self.h)
        fig, axes = plt.subplots(2 if self.w > 1.6 * self.h else 1, 1 if self.w > 1.6 * self.h else 2,
                                 figsize=(16, 16 * (2 * self.h) / self.w + 1.2) if self.w > 1.6 * self.h else (16, 8.4))
        for ax, side in zip(axes, ("top", "bottom")):
            ax.set_facecolor("#0b1a12")
            ax.add_patch(Rectangle((-hw, -hh), self.w, self.h, fill=False, ec="#e0d060", lw=1.5))
            for (x, y, w, h, label, s) in self.blocks:
                if s == side:
                    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, fc="#2a2a40", ec="#8888ff", lw=0.8, ls="--"))
                    ax.text(x, y, label, color="#c8c8ff", ha="center", va="center", fontsize=6)
            lay = "F.Cu" if side == "top" else "B.Cu"
            col = "#d04040" if side == "top" else "#4080e0"
            for (x1, y1, x2, y2, w, l, n) in self.tracks:
                if l == lay:
                    c = "#ffb000" if "CSI" in n else col
                    ax.plot([x1, x2], [y1, y2], color=c, lw=max(w * 900 / scale, 0.4), solid_capstyle="round")
            if side == "top":
                for (s, n, tag) in self.copper["F.Cu"]:
                    if "." not in tag or not tag.startswith("U"):
                        continue
                    c = "#555" if n.startswith("<nc") else ("#40a040" if n == "GND" else
                                                           "#ffb000" if "CSI" in n else "#d06060")
                    if s[0] == "c":
                        ax.add_patch(Circle((s[1], s[2]), s[3], fc=c, ec="none"))
                    else:
                        ax.add_patch(Rectangle((s[1] - s[3], s[2] - s[4]), 2 * s[3], 2 * s[4], fc=c, ec="none"))
            for (x, y, d, n) in self.vias:
                ax.add_patch(Circle((x, y), d / 2, fc="#c0c0c0", ec="#303030", lw=0.2))
            for (ref, s, pads) in self.parts:
                if s != side:
                    continue
                for (px, py, hx, hy, n) in pads:
                    ax.add_patch(Rectangle((px - hx, py - hy), 2 * hx, 2 * hy,
                                           fc="#40a040" if n == "GND" else "#5090ff", ec="none", alpha=0.9))
            for (x, y, d) in self.holes:
                ax.add_patch(Circle((x, y), d / 2, fc="black", ec="#e0d060"))
            if side == "top":
                for (ox, oy, pre) in self.sensors:
                    ax.add_patch(Rectangle((ox - 8.2, oy - 8.2), 16.4, 16.4, fill=False, ec="#60c0ff", ls=":", lw=0.8))
                    ax.text(ox, oy - 8.8, f"{pre + ' ' if pre else ''}lens holder base", color="#60c0ff", ha="center", fontsize=6)
            ax.set_xlim(-hw - 1, hw + 1)
            ax.set_ylim(hh + 1, -hh - 1)
            ax.set_aspect("equal")
            ax.set_title("TOP (F.Cu) - sensor side" if side == "top" else "BOTTOM (B.Cu) - seen from top (not mirrored)", fontsize=10)
        fig.suptitle(title, fontsize=12)
        fig.tight_layout()
        fig.savefig(path, dpi=130)


# ============================================================ footprints
def footprint_body(ref="REF**", value="IMX568_LGA132", net_of=None, nets=None, indent="  "):
    hw, hh = PKG_W / 2, PKG_H / 2
    I = indent
    u = lambda *k: str(uuid.uuid5(_ns, "/".join(map(str, ("fp", ref) + k))))   # noqa: E731
    t = '(stroke (width {w}) (type default)) (fill none) (layer "{l}")'
    g = [f'{I}(property "Reference" "{ref}" (at 0 {-hh - 1.2} 0) (layer "F.SilkS") (uuid "{u("r")}")\n'
         f'{I}  (effects (font (size 1 1) (thickness 0.15))))\n',
         f'{I}(property "Value" "{value}" (at 0 {hh + 1.2} 0) (layer "F.Fab") (uuid "{u("v")}")\n'
         f'{I}  (effects (font (size 1 1) (thickness 0.15))))\n',
         f'{I}(attr smd)\n',
         f'{I}(fp_rect (start {-hw} {-hh}) (end {hw} {hh}) {t.format(w=0.1, l="F.Fab")} (uuid "{u("fab")}"))\n',
         f'{I}(fp_rect (start {-hw - 0.15} {-hh - 0.15}) (end {hw + 0.15} {hh + 0.15}) {t.format(w=0.12, l="F.SilkS")} (uuid "{u("silk")}"))\n',
         f'{I}(fp_rect (start {-hw - 0.5} {-hh - 0.5}) (end {hw + 0.5} {hh + 0.5}) {t.format(w=0.05, l="F.CrtYd")} (uuid "{u("crt")}"))\n',
         f'{I}(fp_circle (center {hw + 0.6} {-hh - 0.6}) (end {hw + 0.85} {-hh - 0.6}) (stroke (width 0.25) (type default)) (fill solid) (layer "F.SilkS") (uuid "{u("p1")}"))\n',
         f'{I}(fp_text user "A1" (at {hw - 1.3} {-hh + 0.9} 0) (layer "F.Fab") (uuid "{u("a1")}") (effects (font (size 0.6 0.6) (thickness 0.1))))\n']
    for (x1, y1, x2, y2, k) in ((-1, 0, 1, 0, "h"), (0, -1, 0, 1, "v")):
        g.append(f'{I}(fp_line (start {x1} {y1}) (end {x2} {y2}) (stroke (width 0.05) (type default)) (layer "F.Fab") (uuid "{u("oc", k)}"))\n')
    for ball in sorted(PINS, key=lambda b: (b[0], int(b[1:]))):
        x, y = ball_xy(ball)
        net = ""
        if net_of:
            n = net_of(ball)
            if n:
                net = f' (net {nets[n]} "{n}")'
        if ball in CORNER_PADS:
            g.append(f'{I}(pad "{ball}" smd rect (at {f(x)} {f(y)}) (size {CORNER} {CORNER}) (layers "F.Cu" "F.Mask")'
                     f' (solder_mask_margin {PAD_MASK}){net} (uuid "{u(ball)}"))\n')
            for i, (dx, dy) in enumerate(((-.4, -.4), (.4, -.4), (-.4, .4), (.4, .4))):
                g.append(f'{I}(pad "" smd rect (at {f(x + dx)} {f(y + dy)}) (size 0.6 0.6) (layers "F.Paste") (uuid "{u(ball, "pp", i)}"))\n')
        else:
            g.append(f'{I}(pad "{ball}" smd circle (at {f(x)} {f(y)}) (size {PAD_D} {PAD_D}) (layers "F.Cu" "F.Mask")'
                     f' (solder_mask_margin {PAD_MASK}){net} (uuid "{u(ball)}"))\n')
            g.append(f'{I}(pad "" smd circle (at {f(x)} {f(y)}) (size {PAD_PASTE_D} {PAD_PASTE_D}) (layers "F.Paste") (uuid "{u(ball, "pp")}"))\n')
    return "".join(g)


def bga_footprint(board, ref, value, x, y, n=16, pitch=0.8, ball_pad=0.40, side="top", note=""):
    """Generic JEDEC BGA (rows A..T without I,O,Q,S), no nets."""
    rows = [r for r in "ABCDEFGHJKLMNPRTUVWY"][:n]
    L = "F" if side == "top" else "B"
    span = (n - 1) * pitch
    body = span + 2 * 0.8
    s = [f'  (footprint "IMX568:BGA-{n * n}_{body:.0f}x{body:.0f}mm_P{pitch}mm" (layer "{L}.Cu") (uuid "{board.uid(ref)}") (at {f(PX + x)} {f(PY + y)})\n',
         f'    (property "Reference" "{ref}" (at 0 {-body / 2 - 1} 0) (layer "{L}.SilkS") (uuid "{board.uid(ref, "r")}") (effects (font (size 1 1) (thickness 0.15))))\n',
         f'    (property "Value" "{value}" (at 0 {body / 2 + 1} 0) (layer "{L}.Fab") (uuid "{board.uid(ref, "v")}") (effects (font (size 0.8 0.8) (thickness 0.12))))\n',
         '    (attr smd)\n',
         f'    (fp_rect (start {-body / 2} {-body / 2}) (end {body / 2} {body / 2}) (stroke (width 0.1) (type default)) (fill none) (layer "{L}.Fab") (uuid "{board.uid(ref, "fab")}"))\n',
         f'    (fp_rect (start {-body / 2 - 0.5} {-body / 2 - 0.5}) (end {body / 2 + 0.5} {body / 2 + 0.5}) (stroke (width 0.05) (type default)) (fill none) (layer "{L}.CrtYd") (uuid "{board.uid(ref, "crt")}"))\n',
         f'    (fp_circle (center {-body / 2 - 0.6} {-body / 2 - 0.6}) (end {-body / 2 - 0.35} {-body / 2 - 0.6}) (stroke (width 0.25) (type default)) (fill solid) (layer "{L}.SilkS") (uuid "{board.uid(ref, "p1")}"))\n']
    if note:
        s.append(f'    (fp_text user "{note}" (at 0 0 0) (layer "{L}.Fab") (uuid "{board.uid(ref, "note")}") (effects (font (size 0.6 0.6) (thickness 0.1))))\n')
    for i, r in enumerate(rows):
        for c in range(n):
            px, py = -span / 2 + c * pitch, -span / 2 + i * pitch
            s.append(f'    (pad "{r}{c + 1}" smd circle (at {f(round(px, 3))} {f(round(py, 3))}) (size {ball_pad} {ball_pad})'
                     f' (layers "{L}.Cu" "{L}.Paste" "{L}.Mask") (uuid "{board.uid(ref, r, c)}"))\n')
            board.copper[f"{L}.Cu"].append((("c", x + px, y + py, ball_pad / 2), f"<{ref}.{r}{c + 1}>", f"{ref}.{r}{c + 1}"))
    s.append('  )\n')
    board.items.append("".join(s))
    board.keepout[side].append((x, y, body + 1.0, body + 1.0))
    board.blocks.append((x, y, body, body, value, side))


def fpc_footprint(board, ref, x, y, pin_nets, side="bottom", rot=0):
    """40-pos 0.5 mm FPC (Hirose FH12-40S-0.5SH class). Geometry approximate:
    run 'Update Footprints from Library' in KiCad to pull the exact library
    footprint (pads keep their nets by pad number)."""
    L = "F" if side == "top" else "B"
    n = len(pin_nets)
    span = (n - 1) * 0.5
    s = [f'  (footprint "Connector_FFC-FPC:Hirose_FH12-{n}S-0.5SH_1x{n}-1MP_P0.50mm_Horizontal" (layer "{L}.Cu") (uuid "{board.uid(ref)}") (at {f(PX + x)} {f(PY + y)} {rot})\n',
         f'    (property "Reference" "{ref}" (at 0 -2.5 {rot}) (layer "{L}.SilkS") (uuid "{board.uid(ref, "r")}") (effects (font (size 0.8 0.8) (thickness 0.12)){" (justify mirror)" if L == "B" else ""}))\n',
         f'    (property "Value" "FH12-{n}S-0.5SH(55)" (at 0 4.5 {rot}) (layer "{L}.Fab") (uuid "{board.uid(ref, "v")}") (effects (font (size 0.6 0.6) (thickness 0.1)){" (justify mirror)" if L == "B" else ""}))\n',
         '    (attr smd)\n',
         f'    (fp_rect (start {-span / 2 - 2.6} -1.0) (end {span / 2 + 2.6} 4.0) (stroke (width 0.1) (type default)) (fill none) (layer "{L}.Fab") (uuid "{board.uid(ref, "fab")}"))\n']
    for i, net in enumerate(pin_nets, 1):
        # pin 1 at +X when the footprint is on the back (mirrored view), -X on top
        px = (-span / 2 + (i - 1) * 0.5) * (1 if side == "top" else -1)
        s.append(f'    (pad "{i}" smd rect (at {f(round(px, 3))} 0) (size 0.3 1.3) (layers "{L}.Cu" "{L}.Paste" "{L}.Mask")'
                 f' (net {board.net(net)} "{net}") (uuid "{board.uid(ref, i)}"))\n')
        board.copper[f"{L}.Cu"].append((("r", x + px, y, 0.15, 0.65), net, f"{ref}.{i}"))
    for k, sx in enumerate((-1, 1)):
        mx = sx * (span / 2 + 1.85)
        s.append(f'    (pad "MP" smd rect (at {f(mx)} 2.9) (size 1.8 2.2) (layers "{L}.Cu" "{L}.Paste" "{L}.Mask")'
                 f' (net {board.net("GND")} "GND") (uuid "{board.uid(ref, "mp", k)}"))\n')
        board.copper[f"{L}.Cu"].append((("r", x + mx, y + 2.9, 0.9, 1.1), "GND", f"{ref}.MP{k}"))
    s.append('  )\n')
    board.items.append("".join(s))
    board.keepout[side].append((x, y + 1.5, span + 6.0, 6.0))
    board.parts.append((ref, side, [(x + (-span / 2 + (i - 1) * 0.5) * (1 if side == "top" else -1), y, 0.15, 0.65, nn)
                                   for i, nn in enumerate(pin_nets, 1)]))


def default_project(fname):
    return {
        "meta": {"filename": fname.replace(".kicad_pcb", ".kicad_pro"), "version": 1},
        "board": {"design_settings": {"rules": {
            "min_clearance": 0.1, "min_track_width": 0.09, "min_via_diameter": 0.4,
            "min_through_hole_diameter": 0.2, "min_hole_to_hole": 0.25,
            "min_copper_edge_clearance": 0.3}}},
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.1, "track_width": 0.12, "via_diameter": 0.4, "via_drill": 0.2,
                 "diff_pair_width": 0.1, "diff_pair_gap": 0.15, "diff_pair_via_gap": 0.3},
                {"name": "CSI2_100R", "clearance": 0.15, "track_width": 0.1, "via_diameter": 0.4, "via_drill": 0.2,
                 "diff_pair_width": 0.1, "diff_pair_gap": 0.15, "diff_pair_via_gap": 0.3},
                {"name": "POWER", "clearance": 0.1, "track_width": 0.2, "via_diameter": 0.4, "via_drill": 0.2},
            ],
            "netclass_patterns": [
                {"netclass": "CSI2_100R", "pattern": "*CSI_*"},
                {"netclass": "POWER", "pattern": "+*"},
                {"netclass": "POWER", "pattern": "*VCP*"},
            ]},
    }
