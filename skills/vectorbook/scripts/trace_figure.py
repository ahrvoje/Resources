#!/usr/bin/env python3
"""Trace scanned DjVu figures into TikZ; requires the adjacent common.py."""
import argparse
import json
import math
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

from common import find_tool, path, render_page_gray, run

DPI = 600
PP = DPI / 72
NEIGH = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
         if (dy, dx) != (0, 0)]


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean(mask):
    """Remove components smaller than twelve pixels."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), 8)
    keep = stats[:, cv2.CC_STAT_AREA] >= 12
    keep[0] = False
    return keep[lab]


def segment(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    box = list(map(int, args.box.split(",")))
    if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("box must be X0,Y0,X1,Y1 with positive extent")
    if min(box) < 0 or args.page < 1:
        raise ValueError("Page is one-based; crop coordinates must be nonnegative")
    x, y, x1, y1 = [v * 2 for v in box]
    # Render the whole page and crop here (ddjvu's -segment measures Y from the bottom).
    full = np.asarray(render_page_gray(args.page, 600, out / "commands.log"))
    ink = clean(full[y:y1, x:x1] < 128)
    if ink.shape != (y1-y, x1-x):
        raise RuntimeError("box lies outside the rendered page")
    Image.fromarray(np.where(ink, 0, 255).astype("uint8")).save(out / "crop600.png")
    n, comp, stats, _ = cv2.connectedComponentsWithStats(ink.astype("uint8"), 8)
    np.save(out / "components.npy", comp.astype("int32"))
    candidates = []
    for i in range(1, n):
        a, b, w, h, area = map(int, stats[i])
        # Hand letters at 600 dpi are up to ~200 px and thin; the vision model sorts
        # labels from drawing parts, so keep every small component as a candidate.
        if max(w, h) < 230:
            candidates.append((i, (a, b, a+w, b+h)))
    parent = list(range(len(candidates)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    elongated = {}
    for i, box in candidates:
        yy, xx = np.nonzero(comp[box[1]:box[3], box[0]:box[2]] == i)
        ev = np.linalg.eigvalsh(np.cov(np.vstack([xx, yy]))) if len(xx) > 2 else np.ones(2)
        # principal-axis elongation also catches diagonal dashes (square bbox)
        elongated[box] = math.sqrt(max(ev[1], 1e-9) / max(ev[0], 1e-9)) >= 3.0

    def dashlike(box):
        return elongated[tuple(box)] if tuple(box) in elongated else False

    # Orchestrator: dash-like pieces (dashes of hidden lines, minus signs) stay singleton
    # clusters, so removing a label never removes the dashed line beside it; the vision
    # model joins a minus sign to its letter by listing both clusters.
    for i, (_, a) in enumerate(candidates):
        for j in range(i):
            b = candidates[j][1]
            if True:  # one component = one mark; the vision model groups marks into labels
                continue
            if (a[0]-28 <= b[2] and b[0]-28 <= a[2] and
                    a[1]-28 <= b[3] and b[1]-28 <= a[3]):
                parent[root(i)] = root(j)
    groups = {}
    for i, item in enumerate(candidates):
        groups.setdefault(root(i), []).append(item)
    clusters = []
    for k, items in enumerate(groups.values(), 1):
        boxes = np.array([b for _, b in items])
        bbox = [*boxes[:, :2].min(0), *boxes[:, 2:].max(0)]
        clusters.append(dict(id=k, bbox=list(map(int, bbox)),
                             components=[i for i, _ in items]))
    dump(out / "seg.json", dict(page=args.page, box=box,
                                size=[ink.shape[1], ink.shape[0]]))
    dump(out / "marks.json", dict(clusters=clusters))
    im = Image.fromarray(np.where(ink, 190, 255).astype("uint8")).convert("RGB")
    im = im.resize((max(1, im.width//2), max(1, im.height//2)))
    # A margin ensures even candidates on the crop edge get unobstructed IDs.
    canvas = Image.new("RGB", (im.width+100, im.height+100), "white")
    canvas.paste(im, (50, 50))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    occupied = []
    for c in clusters:
        x0, y0, x1, y1 = [v/2+50 for v in c["bbox"]]
        color = tuple(int(v) for v in cv2.cvtColor(
            np.uint8([[[(c["id"]*43) % 180, 210, 180]]]),
            cv2.COLOR_HSV2RGB)[0, 0])
        draw.rectangle((x0, y0, x1, y1), outline=color, width=1)
        text = str(c["id"])
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2]+4, tb[3]-tb[1]+4
        choices = [(x0, y0-th-2), (x1+2, y0), (x0, y1+2),
                   (max(0, x0-tw-2), y0)]

        def penalty(p):
            r = (p[0], p[1], p[0]+tw, p[1]+th)
            boxes = occupied + [(x0, y0, x1, y1)]
            return sum(max(0, min(r[2], b[2])-max(r[0], b[0])) *
                       max(0, min(r[3], b[3])-max(r[1], b[1])) for b in boxes)
        px, py = min(choices, key=penalty)
        px, py = max(0, min(px, canvas.width-tw)), max(0, min(py, canvas.height-th))
        occupied.append((px, py, px+tw, py+th))
        draw.rectangle(occupied[-1], fill="white")
        draw.text((px+2, py+2-tb[1]), text, font=font, fill=color)
    canvas.save(out / "marks.png")
    print(f"segment: {ink.shape[1]}x{ink.shape[0]} px, {len(clusters)} clusters")


def length(p):
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


def resample(p, step=2):
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    good = np.r_[True, np.diff(d) > 1e-8]
    d, p = d[good], p[good]
    if len(p) < 2:
        return p
    t = np.linspace(0, d[-1], max(2, int(math.ceil(d[-1]/step))+1))
    return np.column_stack([np.interp(t, d, p[:, i]) for i in (0, 1)])


def unit(v):
    return v / max(np.linalg.norm(v), 1e-12)


def graph_paths(mask, w, stats=None):
    """Emit every graph branch exactly once, including self-loops.

    Junction pixels remain individual nodes: contracting a junction cluster
    would otherwise hide its internal skeleton length. Only terminal branches
    shorter than 1.5 w are pruned, in a single pass.
    """
    sk = skeletonize(mask)
    pixels = set(map(tuple, np.argwhere(sk)))
    adj = {}
    for y, x in sorted(pixels):
        ns = []
        for dy, dx in NEIGH:
            q = (y+dy, x+dx)
            if q not in pixels:
                continue
            # Avoid redundant diagonal edges at digital right-angle turns.
            if dy and dx and ((y, x+dx) in pixels or (y+dy, x) in pixels):
                continue
            ns.append(q)
        adj[y, x] = ns
    nodes = {p for p in pixels if len(adj[p]) != 2}
    seen, branches = set(), []

    def key(a, b):
        return tuple(sorted((a, b)))

    def walk(p, q):
        pts = [p, q]
        seen.add(key(p, q))
        prev, cur = p, q
        while cur not in nodes and cur != p:
            nxt = next((r for r in adj[cur] if r != prev), None)
            if nxt is None or key(cur, nxt) in seen:
                break
            seen.add(key(cur, nxt))
            pts.append(nxt)
            prev, cur = cur, nxt
        return np.array(pts, float)[:, ::-1], cur

    for p in sorted(nodes):
        for q in adj[p]:
            if key(p, q) not in seen:
                arr, end = walk(p, q)
                terminal = len(adj[p]) == 1 or len(adj[end]) == 1
                branches.append((arr, p, end,
                                 terminal and length(arr) < 1.5*w))
    # Components with degree two everywhere are closed cycles.
    for p in sorted(pixels):
        for q in adj[p]:
            if key(p, q) not in seen:
                arr, end = walk(p, q)
                branches.append((arr, p, end, False))

    total = sum(length(p) for p, _, _, pruned in branches if not pruned)
    paths = []
    for p, a, b, pruned in branches:
        if pruned:
            continue
        paths.append(dict(p=p,
                          isolated=len(adj[a]) < 3 and len(adj[b]) < 3,
                          closed=np.linalg.norm(p[0]-p[-1]) < .1))
    emitted = sum(length(t["p"]) for t in paths)
    assert emitted + 1e-8 >= .95*total, (
        f"Skeleton coverage lost: emitted {emitted:.3f} px / {total:.3f} px")
    if stats is not None:
        stats.update(skeleton_length_after_pruning_px=total,
                     emitted_path_length_px=emitted)
    print(f"skeleton: emitted {emitted:.3f} px / "
          f"{total:.3f} px after pruning")
    return paths


def blobs(mask, dt, w):
    core, n = ndi.label(dt > .8*w)  # line centres reach only ~0.5 w
    result, removal = [], np.zeros_like(mask)
    for i in range(1, n+1):
        c = core == i
        area_core = int(c.sum())
        if area_core <= (.35*w)**2 or dt[c].max() < 1.15*w:
            continue  # true dots peak at >= 1.2 w; arrow tips and corners at <= 1.14 w
        # Use pixel corners, not just pixel centres, for the core rectangle.
        yy, xx = np.nonzero(c)
        points = np.column_stack([xx, yy]).astype("float32")
        hull = cv2.convexHull(points).reshape(-1, 2)
        corners = np.concatenate([
            hull + np.array([dx, dy], dtype="float32")
            for dx, dy in ((-.5, -.5), (-.5, .5), (.5, -.5), (.5, .5))
        ])
        sides = sorted(cv2.minAreaRect(corners)[1])
        short, long = sides
        rect_area = short*long
        if (short <= 0 or long/short > 2.2 or
                area_core < .45*rect_area or long > 6*w):
            continue
        # Orchestrator: a crossing of two lines is thick but has 4 arms; dots have <= 3
        # (a curve through the dot plus at most one vector starting there).
        cy, cx = np.mean(np.nonzero(c), axis=1)
        ang = np.linspace(0, 2*math.pi, 144, endpoint=False)
        ry = np.clip(np.round(cy + 2.5*w*np.sin(ang)).astype(int), 0, mask.shape[0]-1)
        rx = np.clip(np.round(cx + 2.5*w*np.cos(ang)).astype(int), 0, mask.shape[1]-1)
        ring = mask[ry, rx].astype(int)
        if int(np.sum(np.diff(np.r_[ring, ring[:1]]) == 1)) >= 4:
            continue
        distance = ndi.distance_transform_edt(~c)
        region = mask & (distance <= w)
        removal |= distance <= .5*w
        contours, _ = cv2.findContours(region.astype("uint8"),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            p = contour[:, 0, :].astype(float)
            if len(p) < 3:
                continue
            p = ndi.gaussian_filter1d(p, max(.6, .15*w), axis=0, mode="wrap")
            poly = cv2.approxPolyDP(p.astype("float32").reshape(-1, 1, 2),
                                   .3*w, True)[:, 0]
            area = abs(cv2.contourArea(p.astype("float32")))
            perimeter = cv2.arcLength(p.astype("float32").reshape(-1, 1, 2), True)
            roundish = (4*math.pi*area/max(perimeter**2, 1) > .75
                        and np.ptp(p, axis=0).max() < 4*w)
            result.append(dict(p=poly, circle=roundish,
                               center=p.mean(0), radius=math.sqrt(area/math.pi)))
    return result, mask & ~removal


def dash_chains(paths, w):
    """Join mutually compatible isolated dashes without absorbing hatch ticks."""
    candidates = [i for i, t in enumerate(paths)
                  if t["isolated"] and not t["closed"] and length(t["p"]) < 8*w]
    options = []
    for k, i in enumerate(candidates):
        for j in candidates[:k]:
            for a in (0, 1):
                for b in (0, 1):
                    p = paths[i]["p"][::(-1 if a else 1)]
                    q = paths[j]["p"][::(-1 if b else 1)]
                    gap = q[0]-p[-1]
                    dist = np.linalg.norm(gap)
                    u, v = unit(p[-1]-p[0]), unit(q[-1]-q[0])
                    cos = math.cos(math.radians(30))
                    if (dist < 6*w and np.dot(u, v) > cos and
                            np.dot(u, unit(gap)) > cos and
                            np.dot(v, unit(gap)) > cos):
                        options.append((dist, (i, 1-a), (j, b)))
    links = {}
    for _, a, b in sorted(options):
        if a not in links and b not in links:
            links[a], links[b] = b, a
    used, removed, chains = set(), set(), []
    starts = [(i, e) for i in candidates for e in (0, 1) if (i, e) not in links]
    for i, e in starts:
        if i in used:
            continue
        ids, pieces = [], []
        while i not in used:
            used.add(i)
            ids.append(i)
            pieces.append(paths[i]["p"][::-1] if e else paths[i]["p"])
            nxt = links.get((i, 1-e))
            if nxt is None:
                break
            i, e = nxt
        if len(ids) >= 3:
            removed.update(ids)
            chains.append(dict(p=np.concatenate(pieces), closed=False,
                               isolated=True, style="mm hidden"))
    return [t for i, t in enumerate(paths) if i not in removed] + chains, len(chains)


def split_corners(p, closed, w):
    p = resample(p)
    if len(p) < 4:
        return [(p, closed)]
    if closed:
        p = p[:-1]
    n, r = len(p), max(1, round(w))
    angles = np.zeros(n)
    for i in range(n):
        if not closed and (i < r or i+r >= n):
            continue
        a, b = p[i]-p[(i-r) % n], p[(i+r) % n]-p[i]
        angles[i] = math.acos(np.clip(np.dot(unit(a), unit(b)), -1, 1))
    peaks = []
    for i in sorted(range(n), key=lambda j: (-angles[j], j)):
        if angles[i] <= math.pi/4:
            break
        if all(min(abs(i-j), n-abs(i-j)) > r if closed else abs(i-j) > r
               for j in peaks):
            peaks.append(i)
    peaks.sort()
    if not peaks:
        return [(np.vstack([p, p[0]]) if closed else p, closed)]
    if closed:
        return [(np.array([p[k % n] for k in range(a, b+1)]), False)
                for a, b in zip(peaks, peaks[1:]+[peaks[0]+n])]
    cuts = [0]+[i for i in peaks if 0 < i < n-1]+[n-1]
    return [(p[a:b+1], False) for a, b in zip(cuts, cuts[1:])]


def bezier_fit(p, error):
    """Schneider least-squares cubic fitting with Newton reparameterization."""
    def bez(b, t):
        t = np.asarray(t)[..., None]
        return ((1-t)**3*b[0]+3*t*(1-t)**2*b[1]+
                3*t*t*(1-t)*b[2]+t**3*b[3])

    def fit(q, left, right, depth=0):
        if len(q) == 2:
            d = np.linalg.norm(q[-1]-q[0])/3
            return [np.array([q[0], q[0]+left*d, q[-1]+right*d, q[-1]])]
        u = np.r_[0, np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))]
        if u[-1] < 1e-9:
            return []
        u /= u[-1]
        best = None
        for attempt in range(5):
            t = u[:, None]
            a = np.stack([3*t*(1-t)**2*left, 3*t*t*(1-t)*right], axis=1)
            base = ((1-t)**3+3*t*(1-t)**2)*q[0] + (
                t**3+3*t*t*(1-t))*q[-1]
            alpha = np.linalg.lstsq(a.reshape(-1, 2, 2).transpose(0, 2, 1)
                                    .reshape(-1, 2),
                                    (q-base).reshape(-1), rcond=None)[0]
            d = np.linalg.norm(q[-1]-q[0])
            if np.min(alpha) < 1e-6*d:
                alpha[:] = d/3
            b = np.array([q[0], q[0]+left*alpha[0],
                          q[-1]+right*alpha[1], q[-1]])
            residual = np.linalg.norm(bez(b, u)-q, axis=1)
            split = int(np.argmax(residual))
            best = (b, split)
            if residual[split] <= error:
                return [b]
            if attempt == 4:
                break
            first = 3*np.diff(b, axis=0)
            second = 2*np.diff(first, axis=0)
            v = ((1-t)**2*first[0]+2*t*(1-t)*first[1]+t*t*first[2])
            acc = (1-t)*second[0]+t*second[1]
            diff = bez(b, u)-q
            den = (v*v+diff*acc).sum(1)
            proposal = u - np.divide((diff*v).sum(1), den,
                                      out=np.zeros_like(u), where=abs(den) > 1e-12)
            if np.any(np.diff(proposal) <= 0):
                break
            u = np.clip(proposal, 0, 1)
        b, split = best
        split = max(1, min(len(q)-2, split))
        if depth > 40:
            return [np.array([a, a+(b-a)/3, a+2*(b-a)/3, b])
                    for a, b in zip(q, q[1:])]
        tangent = unit(q[split-1]-q[split+1])
        return fit(q[:split+1], left, tangent, depth+1) + fit(
            q[split:], -tangent, right, depth+1)
    return fit(p, unit(p[1]-p[0]), unit(p[-2]-p[-1]))


def geometry(paths, w):
    result = []
    for path in paths:
        pieces = []
        for p, closed in split_corners(path["p"], path["closed"], w):
            p = resample(p)
            if len(p) < 2:
                continue
            if closed:
                q = ndi.gaussian_filter1d(p[:-1], max(.1, w/2), axis=0, mode="wrap")
                q = np.vstack([q, q[0]])
            else:
                q = ndi.gaussian_filter1d(p, max(.1, w/2), axis=0, mode="nearest")
                # Remove endpoint drift without creating discontinuities.
                t = np.linspace(0, 1, len(q))[:, None]
                q += (1-t)*(p[0]-q[0])+t*(p[-1]-q[-1])
            chord = q[-1]-q[0]
            distance = np.abs(chord[0]*(q-q[0])[:, 1] - chord[1]*(q-q[0])[:, 0]) / max(np.linalg.norm(chord), 1e-9)
            if not closed and distance.max() <= .5*w:
                pieces.append(("line", q[[0, -1]]))
            else:
                pieces.extend(("curve", b) for b in bezier_fit(q, .5*w))
        if pieces:
            result.append(dict(pieces=pieces, closed=path["closed"], style=path["style"]))
    return result


def label_rect(label):
    """Typeset node bounds, including its requested TikZ anchor."""
    x, y = label["pos"] + label["shift"]
    w, h = label["dims"]
    anchor = label["anchor"]
    fx = 0 if "west" in anchor else 1 if "east" in anchor else .5
    fy = 0 if "south" in anchor else 1 if "north" in anchor else .5
    return np.array([x-fx*w, y-fy*h, x+(1-fx)*w, y+(1-fy)*h])


def write_figure(out, geo, regions, labels, scale, height, bounds):
    def xy(p):
        return np.array([p[0]*scale, (height-p[1])*scale])

    def pt(p):
        return f"({p[0]:.2f},{p[1]:.2f})"
    # \csname keeps the \if-switch token out of skipped text (a bare \ifmm... breaks \fi nesting).
    text = [r"\expandafter\ifx\csname ifmmfiglabels\endcsname\relax",
            r"\expandafter\newif\csname ifmmfiglabels\endcsname \mmfiglabelstrue \fi",
            r"\expandafter\ifx\csname ifmmfigstrokes\endcsname\relax",
            r"\expandafter\newif\csname ifmmfigstrokes\endcsname \mmfigstrokestrue \fi",
            r"\begin{tikzpicture}[x=1pt,y=1pt]",
            r"\useasboundingbox "+pt(bounds[:2])+r" rectangle "+pt(bounds[2:])+";",
            r"\ifmmfigstrokes"]
    for path in geo:
        pieces = path["pieces"]
        s = r"\draw["+path["style"]+"] "+pt(xy(pieces[0][1][0]))
        for kind, b in pieces:
            if kind == "line":
                s += " -- "+pt(xy(b[-1]))
            else:
                s += " .. controls "+pt(xy(b[1]))+" and "+pt(xy(b[2]))+" .. "+pt(xy(b[3]))
        text.append(s+(" -- cycle;" if path["closed"] else ";"))
    for blob in regions:
        if blob["circle"]:
            text.append(r"\fill[mmink] "+pt(xy(blob["center"]))+
                        f" circle[radius={blob['radius']*scale:.2f}pt];")
        else:
            text.append(r"\fill[mmink] "+" -- ".join(pt(xy(p)) for p in blob["p"])+
                        " -- cycle;")
    text.extend([r"\fi", "% LABELS", r"\ifmmfiglabels"])
    for label in labels:
        text.append(r"\node[mm label, anchor="+label["anchor"]+"] at "+
                    pt(label["pos"]+label["shift"])+" {"+label["tex"]+"};")
    text.extend([r"\fi", r"\end{tikzpicture}"])
    (out / "fig.tex").write_text("\n".join(text)+"\n", encoding="utf-8")


def render_checks(out, labels):
    """Compile three views; red rules record the picture box location."""
    folder = out / "check"
    folder.mkdir(exist_ok=True)
    shutil.copy2(path("style"), folder / path("style").name)
    images, rectangles, dimensions = {}, {}, {}
    for name, strokes, lettering in (("strokes", True, False),
                                     ("labels", False, True), ("both", True, True)):
        measurements = []
        if name == "both":
            for i, label in enumerate(labels):
                measurements.append(
                    r"\setbox2=\hbox{\tikz\node[mm label] {"+label["tex"]+r"};}"
                    +r"\typeout{TRACE-DIM-"+str(i)+r":\the\wd2,\the\ht2,\the\dp2}")
        switches = (r"\mmfigstrokestrue" if strokes else r"\mmfigstrokesfalse")
        switches += (r"\mmfiglabelstrue" if lettering else r"\mmfiglabelsfalse")
        doc = "\n".join([
            r"\documentclass{article}", r"\usepackage{" + path("style").stem + "}",
            r"\pagestyle{empty}", r"\newif\ifmmfiglabels",
            r"\newif\ifmmfigstrokes", r"\begin{document}",
            *measurements, switches + r"\setbox0=\hbox{\input{../fig}}%", r"\noindent",
            # red rules mark the box: bottom rule ends at the box bottom, top rule starts at the box top
            r"\leavevmode\rlap{\textcolor{red}{\rule[-\dp0]{\wd0}{0.5pt}}}"
            r"\rlap{\textcolor{red}{\rule[\ht0]{\wd0}{0.5pt}}}\box0",
            r"\end{document}"])
        (folder / f"{name}.tex").write_text(doc, encoding="utf-8")
        run([find_tool("xelatex"), "-interaction=nonstopmode", "-halt-on-error",
             f"{name}.tex"], folder, folder / "commands.log")
        with pymupdf.open(folder / f"{name}.pdf") as pdf:
            if len(pdf) != 1:
                raise RuntimeError("Check document overflowed one page; reduce figure size")
            page = pdf[0]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(PP, PP),
                                  colorspace=pymupdf.csRGB, alpha=False)
            rgb = np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.width, 3).astype(int)
            red = (rgb[..., 0] - rgb[..., 1] > 40) & (rgb[..., 0] - rgb[..., 2] > 40)  # incl. anti-aliased edges
            ry, rx = np.nonzero(red)
            if not len(ry):
                raise RuntimeError("box marks not found in the check render")
            rows = np.unique(ry)
            top_rule = rows[rows < rows.mean()]
            rectangles[name] = np.array([rx.min()/PP, (top_rule.max()+1)/PP,
                                         (rx.max()+1)/PP, (rows.max()+1)/PP])
            gray = rgb.mean(axis=2)
            images[name] = (gray < 180) & ~red
        if name == "both":
            log = (folder / "both.log").read_text(encoding="utf-8", errors="replace")
            for i, a, b, c in re.findall(
                    r"TRACE-DIM-(\d+):([\d.]+)pt,([\d.]+)pt,([\d.]+)pt", log):
                dimensions[int(i)] = np.array([float(a), float(b)+float(c)]) * 72/72.27
    if any(np.max(abs(rectangles[k]-rectangles["both"])) > .05 for k in rectangles):
        raise RuntimeError("Check pictures have inconsistent bounding-box origins")
    if not images["both"].any():
        raise RuntimeError("Rendered figure is empty")
    # Ink extent is also recorded for inspection, independently of the red rules.
    yy, xx = np.nonzero(images["both"])
    dump(folder / "ink-box.json", [int(xx.min()), int(yy.min()),
                                  int(xx.max()+1), int(yy.max()+1)])
    return images, rectangles["both"], dimensions


def pixel_box(rect, origin, bounds, shape):
    x0, y0, _, y1 = bounds
    a = np.array([(rect[0]-x0+origin[0])*PP,
                  (y1-rect[3]+origin[1])*PP,
                  (rect[2]-x0+origin[0])*PP,
                  (y1-rect[1]+origin[1])*PP])
    a = np.r_[np.floor(a[:2]), np.ceil(a[2:])].astype(int)
    a[[0, 2]] = np.clip(a[[0, 2]], 0, shape[1])
    a[[1, 3]] = np.clip(a[[1, 3]], 0, shape[0])
    return a


def rect_clearance(a, b):
    gap = np.maximum(0., np.maximum(a[:2]-b[2:], b[:2]-a[2:]))
    return float(np.linalg.norm(gap))


def clearance_fix(images, origin, bounds, labels, move):
    """Search 24 directions, in 0.5 pt steps to a total shift of 14 pt.

    Measured label boxes are used conservatively for both kinds of clearance.
    Candidate shifts are absolute, so repeated passes cannot exceed 14 pt.
    """
    strokes = images["strokes"]
    shape = strokes.shape
    if strokes.any():
        distance, nearest = ndi.distance_transform_edt(
            ~strokes, return_indices=True)
        distance /= PP
    else:
        distance = np.full(shape, np.inf)
        nearest = None
    reports = []
    for i, label in enumerate(labels):
        current = label["shift"].copy()
        base_rect = label_rect(label)-np.tile(current, 2)
        center = (base_rect[:2]+base_rect[2:])/2
        px = int(round((center[0]-bounds[0]+origin[0])*PP))
        py = int(round((bounds[3]-center[1]+origin[1])*PP))
        px = int(np.clip(px, 0, shape[1]-1))
        py = int(np.clip(py, 0, shape[0]-1))
        away = np.zeros(2)
        if nearest is not None:
            sy, sx = nearest[:, py, px]
            away = unit(np.array([px-sx, sy-py], float))

        def score(shift):
            rect = base_rect+np.tile(shift, 2)
            # Orchestrator: measure from the text box (node box minus the 2 pt inner sep);
            # bounds grow to include labels later, so they do not limit the search.
            x0, y0, x1, y1 = pixel_box(rect+np.array([2., 2., -2., -2.]), origin, bounds, shape)
            if x1 <= x0 or y1 <= y0:
                return -1., -1.
            # Subtract a pixel diagonal for conservative raster uncertainty.
            stroke_gap = max(0., float(distance[y0:y1, x0:x1].min())
                             - math.sqrt(2)/PP)
            label_gap = min((rect_clearance(rect, label_rect(other))
                             for j, other in enumerate(labels) if j != i),
                            default=math.inf)
            return stroke_gap, label_gap

        def feasible(value):
            return value[0] >= 2.0 and value[1] >= 2.  # 2 pt: clear of lines, close to its point

        chosen = current
        if move:
            zero = np.zeros(2)
            if feasible(score(zero)):
                chosen = zero
            else:
                found = False
                # The first feasible radius is the minimum sampled shift.
                for radius in np.arange(.5, 14.01, .5):
                    choices = []
                    for angle in np.arange(24)*2*math.pi/24:
                        shift = radius*np.array([math.cos(angle), math.sin(angle)])
                        value = score(shift)
                        if feasible(value):
                            choices.append((float(np.dot(unit(shift), away)),
                                            min(value[0]-2.0, value[1]-2),
                                            shift))
                    if choices:
                        chosen = max(choices, key=lambda v: (v[0], v[1]))[2]
                        found = True
                        break
                if not found:
                    # Orchestrator: take the sampled position with the largest clearance;
                    # the report still marks the label as failing.
                    best = max(((min(score(r*np.array([math.cos(a), math.sin(a)]))[0], 9.),
                                 -r, r*np.array([math.cos(a), math.sin(a)]))
                                for r in np.arange(0, 14.01, .5)
                                for a in np.arange(24)*2*math.pi/24),
                               key=lambda v: (v[0], v[1]))
                    chosen = best[2]
            label["shift"] = chosen.copy()
        stroke_gap, label_gap = score(label["shift"])
        reports.append(dict(
            id=i+1, clearance_pt=stroke_gap,
            stroke_clearance_pt=stroke_gap,
            label_clearance_pt=(label_gap if math.isfinite(label_gap) else None),
            shift_pt=label["shift"].tolist(),
            shift_length_pt=float(np.linalg.norm(label["shift"])),
            clearance_ok=feasible((stroke_gap, label_gap))))
    return reports


def fidelity(out, source, images, origin, bounds, scale):
    """Align by the recorded PDF origin, not by best-fit image registration."""
    h, w = source.shape
    # Inverse mapping avoids allocating a second full-size transformed source.
    ox = (origin[0]-bounds[0])*PP
    oy = (origin[1]+bounds[3]-h*scale)*PP
    matrix = np.array([[scale*PP, 0, ox], [0, scale*PP, oy]])
    shape = images["strokes"].shape
    src = cv2.warpAffine(source.astype("uint8"), matrix,
                         (shape[1], shape[0]), flags=cv2.INTER_NEAREST) > 0
    rendered = images["strokes"]
    a, b = skeletonize(src), skeletonize(rendered)

    def distances(x, y):
        if not x.any() or not y.any():
            return dict(mean_pt=None, p95_pt=None)
        values = ndi.distance_transform_edt(~y)[x]/PP
        return dict(mean_pt=float(values.mean()),
                    p95_pt=float(np.percentile(values, 95)))
    metrics = dict(source_to_render=distances(a, b), render_to_source=distances(b, a))
    overlay = np.full((*shape, 3), 255, np.uint8)
    overlay[src] = (245, 170, 170)
    overlay[rendered] = (0, 0, 0)
    overlay[images["labels"]] = (40, 80, 220)
    union = src | images["both"]
    yy, xx = np.nonzero(union)
    if len(xx):
        pad = round(5*PP)
        overlay = overlay[max(0, yy.min()-pad):yy.max()+pad+1,
                          max(0, xx.min()-pad):xx.max()+pad+1]
    Image.fromarray(overlay).save(out / "overlay.png")
    return metrics


def protected_components(ink, comp, w):
    """Protect filled dots and ink touching a long component's bbox centreline."""
    boxes = {}
    slices = ndi.find_objects(comp)
    for i, sl in enumerate(slices, 1):
        if sl is None:
            continue
        ys, xs = sl
        boxes[i] = (xs.start, ys.start, xs.stop, ys.stop)
    long_lines = []
    protected = set()
    for i, (x0, y0, x1, y1) in boxes.items():
        bw, bh = x1-x0, y1-y0
        area = int(np.count_nonzero(comp[y0:y1, x0:x1] == i))
        # a solid disc fills ~0.785 of its box; hand letters fill much less
        if (area/(bw*bh) >= .68 and max(bw, bh)/min(bw, bh) <= 1.3
                and 1.2*w <= max(bw, bh) <= 5*w):
            protected.add(i)
        # Long, elongated components supply drawing centreline segments.
        if max(bw, bh) >= max(230, 12*w) and max(bw, bh) >= 2.2*min(bw, bh):
            protected.add(i)
            if bw >= bh:
                long_lines.append((True, x0, x1, (y0+y1-1)/2))
            else:
                long_lines.append((False, y0, y1, (x0+x1-1)/2))
    # Orchestrator: the centreline rule kept hand letters (a long arc's bbox centreline
    # crosses them), so only filled dots and long strokes are protected.
    return protected


def expand_label_bounds(bounds, labels, margin):
    for label in labels:
        rect = label_rect(label)
        bounds[:2] = np.minimum(bounds[:2], rect[:2]-margin)
        bounds[2:] = np.maximum(bounds[2:], rect[2:]+margin)
    return np.r_[np.floor(bounds[:2]*100)/100,
                 np.ceil(bounds[2:]*100)/100]


def trace(args):
    out = Path(args.dir).resolve()
    ink = np.asarray(Image.open(out / "crop600.png").convert("L")) < 128
    comp = np.load(out / "components.npy", allow_pickle=False)
    if comp.shape != ink.shape or comp.dtype != np.int32:
        raise ValueError("components.npy does not match crop600.png")
    clusters = {c["id"]: c for c in read(out / "marks.json")["clusters"]}
    spec = read(Path(args.labels))
    removed, labels = set(), []
    anchors = {"center", "north", "south", "east", "west",
               "north east", "north west", "south east", "south west"}
    for item in spec.get("labels", []):
        ids = item["clusters"]
        if not ids:
            raise ValueError("Each label must specify at least one cluster")
        if item.get("anchor", "center") not in anchors:
            raise ValueError("Unsupported label anchor")
        if removed.intersection(ids):
            raise ValueError("A cluster occurs in more than one label")
        boxes = np.array([clusters[i]["bbox"] for i in ids])
        bbox = np.r_[boxes[:, :2].min(0), boxes[:, 2:].max(0)]
        labels.append(dict(tex=item["tex"], anchor=item.get("anchor", "center"),
                           pixel=(bbox[:2]+bbox[2:])/2,
                           shift=np.zeros(2), dims=np.array([0., 0.])))
        removed.update(ids)
    removed.update(spec.get("erase", []))
    # Estimate pen width before removal so drawing components in a label
    # cluster can be protected before any pixels are deleted.
    initial_dt = ndi.distance_transform_edt(ink)
    initial_sk = skeletonize(ink)
    if not initial_sk.any():
        raise ValueError("No drawing ink remains after removing labels")
    initial_w = max(1., 2*float(np.median(initial_dt[initial_sk])))
    protected = protected_components(ink, comp, initial_w)
    component_ids = {j for i in removed for j in clusters[i]["components"]}
    component_ids.difference_update(protected)
    # Erased clusters (captions, noise) lose all their ink, protected or not.
    component_ids.update(j for i in spec.get("erase", []) for j in clusters[i]["components"])
    # Keep original drawing pixels exactly; no inpainting or line displacement.
    source = clean(ink & ~np.isin(comp, list(component_ids)))
    if not source.any():
        raise ValueError("No drawing ink remains after removing labels")
    dt = ndi.distance_transform_edt(source)
    sk = skeletonize(source)
    w = max(1., 2*float(np.median(dt[sk])))
    regions, lines = blobs(source, dt, w)
    # Orchestrator: an isolated small solid component is a dot even when it is no thicker
    # than a stroke (e.g. a pole marked by a 1.7 w dot); its skeleton would be pruned away.
    n_c, lab_c, st_c, cen_c = cv2.connectedComponentsWithStats(lines.astype("uint8"), 8)
    for i in range(1, n_c):
        _, _, bw, bh, area = st_c[i]
        if (max(bw, bh) <= 3*w and min(bw, bh) >= w and area >= .6*bw*bh
                and max(bw, bh) <= 1.5*min(bw, bh)):
            regions.append(dict(p=None, circle=True, center=cen_c[i],
                                radius=math.sqrt(area/math.pi)))
            lines = lines & (lab_c != i)
    skeleton_stats = {}
    paths = graph_paths(lines, w, skeleton_stats)
    paths, chain_count = dash_chains(paths, w)
    for path in paths:
        if path.get("style") == "mm hidden":
            continue
        p = np.rint(path["p"]).astype(int)
        widths = 2*dt[np.clip(p[:, 1], 0, ink.shape[0]-1),
                      np.clip(p[:, 0], 0, ink.shape[1]-1)]
        thin_tick = path["isolated"] and length(path["p"]) < 8*w
        path["style"] = ("mm main" if np.median(widths) >= .8*w and not thin_tick
                         else "mm thin")
    geo = geometry(paths, w)
    height, width = ink.shape
    scale = args.width_pt/width
    if args.max_height_pt:
        scale = min(scale, args.max_height_pt/height)
    for label in labels:
        x, y = label["pixel"]
        label["pos"] = np.array([x*scale, (height-y)*scale])
    bounds = np.array([0., 0., width*scale, height*scale])
    write_figure(out, geo, regions, labels, scale, height, bounds)
    images, origin, dims = render_checks(out, labels)
    for i, label in enumerate(labels):
        if i not in dims:
            raise RuntimeError(f"Could not measure typeset label {i+1}")
        label["dims"] = dims[i]
    # Reserve the complete search envelope plus the required 2 pt margin.
    # This prevents crop boundaries from excluding otherwise valid shifts.
    bounds = expand_label_bounds(bounds, labels, 16.02)
    for _ in range(3):
        write_figure(out, geo, regions, labels, scale, height, bounds)
        images, origin, _ = render_checks(out, labels)
        old = np.array([v["shift"].copy() for v in labels])
        reports = clearance_fix(images, origin, bounds, labels, True)
        new = np.array([v["shift"] for v in labels])
        bounds = expand_label_bounds(bounds, labels, 2.02)
        if np.array_equal(old, new):
            break
    # Include every measured label box after all shifts, plus 2 pt.
    bounds = expand_label_bounds(bounds, labels, 2.02)
    # A final verification always measures the written, compiled final positions.
    write_figure(out, geo, regions, labels, scale, height, bounds)
    images, origin, _ = render_checks(out, labels)
    reports = clearance_fix(images, origin, bounds, labels, False)
    metrics = fidelity(out, source, images, origin, bounds, scale)
    ok = (all(v["clearance_ok"] for v in reports) and
          all(v["p95_pt"] is not None and v["p95_pt"] <= 1.2
              for v in metrics.values()))
    result = dict(w_px=w, scale=scale, paths_per_style=dict(Counter(
        p["style"] for p in geo)), blobs=len(regions), dash_chains=chain_count,
        labels=reports, chamfer=metrics, bounding_box_pt=bounds.tolist(),
        **skeleton_stats, ok=ok)
    dump(out / "trace.json", result)
    label_summary = "; ".join(
        f"L{v['id']}={v['clearance_pt']:.2f}pt "
        f"shift({v['shift_pt'][0]:.2f},{v['shift_pt'][1]:.2f})"
        for v in reports)
    print(f"trace: {'OK' if ok else 'CHECK FAILED'}; {len(geo)} paths, "
          f"{len(regions)} blobs, {chain_count} dash chains"
          + ("; "+label_summary if label_summary else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("segment", help="Render and identify candidate lettering")
    p.add_argument("--page", required=True, type=int)
    p.add_argument("--box", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=segment)
    p = sub.add_parser("trace", help="Trace strokes and replace selected lettering")
    p.add_argument("--dir", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--width-pt", required=True, type=float)
    p.add_argument("--max-height-pt", type=float)
    p.set_defaults(func=trace)
    args = parser.parse_args()
    try:
        if args.command == "trace":
            for value in (args.width_pt, args.max_height_pt):
                if value is not None and (not math.isfinite(value) or value <= 0):
                    raise ValueError("Figure dimensions must be finite and positive")
        args.func(args)
    except (OSError, ValueError, KeyError, RuntimeError, cv2.error) as exc:
        print(f"trace_figure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
