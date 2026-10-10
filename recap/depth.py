"""A small perspective renderer for the 3D cards.

Matplotlib's ``mplot3d`` is slow per frame and cannot depth-sort patches from
different artists, so the 3D scenes project their own geometry instead:

* World space is metres. ``X`` runs 0-105 along the pitch toward the goal the
  home side attacks, ``Y`` runs 0-68 across it with high values on that
  side's left touchline (WhoScored ``y``), ``Z`` is height.
* ``Camera`` turns world points into output pixels. Every 3D card draws into
  one pixel-space ``stage`` axes so circles stay round on any frame size.
* ``Painter`` collects shaded faces, sorts them far-to-near and flushes them
  as a single ``PolyCollection`` per layer.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba

from . import theme

PITCH_X = 105.0
PITCH_Y = 68.0
GOAL_HALF_W = 3.66
GOAL_H = 2.44
GOAL_DEPTH = 1.8

# World-space light: from behind the camera's left shoulder and above.
_LIGHT = np.array([-0.38, 0.52, 0.76])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def world_x(pct: float) -> float:
    return float(pct) * PITCH_X / 100.0


def world_y(pct: float) -> float:
    return float(pct) * PITCH_Y / 100.0


def goal_mouth_world(goal_mouth_y: float, goal_mouth_z: float) -> tuple[float, float]:
    """WhoScored goal-mouth (y, z) on the goal plane, in metres.

    Mouth ``y`` shares the pitch-width scale; ``z`` 38 is the crossbar.
    """
    return world_y(goal_mouth_y), float(goal_mouth_z) / 38.0 * GOAL_H


class Camera:
    """Look-at perspective camera that projects metres to output pixels."""

    def __init__(self, target: Sequence[float], *, azimuth: float, elevation: float,
                 distance: float, fov: float = 30.0, center: tuple[float, float] = (0.5, 0.5),
                 zoom: float = 1.0) -> None:
        self.target = np.asarray(target, dtype=float)
        az, el = math.radians(azimuth), math.radians(elevation)
        offset = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        self.eye = self.target + offset * float(distance)
        forward = self.target - self.eye
        self.forward = forward / np.linalg.norm(forward)
        right = np.cross(self.forward, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(right) < 1e-6:
            right = np.array([0.0, -1.0, 0.0])
        self.right = right / np.linalg.norm(right)
        self.up = np.cross(self.right, self.forward)
        self.focal = (theme.FRAME_H / 2.0) / math.tan(math.radians(fov) / 2.0) * float(zoom)
        self.cx = center[0] * theme.FRAME_W
        self.cy = center[1] * theme.FRAME_H

    def project(self, points: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(N, 3) world points to pixel x, pixel y and view depth."""
        pts = np.atleast_2d(np.asarray(points, dtype=float))
        rel = pts - self.eye
        depth = rel @ self.forward
        safe = np.maximum(depth, 0.05)
        sx = self.cx + (rel @ self.right) / safe * self.focal
        sy = self.cy + (rel @ self.up) / safe * self.focal
        return sx, sy, depth

    def point(self, x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        sx, sy, _ = self.project([[x, y, z]])
        return float(sx[0]), float(sy[0])

    def depth_of(self, x: float, y: float, z: float = 0.0) -> float:
        return float(self.project([[x, y, z]])[2][0])

    def pixels_per_metre(self, x: float, y: float, z: float = 0.0) -> float:
        """Screen scale at a world point, for sizing 2D markers in 3D space."""
        depth = max(0.05, self.depth_of(x, y, z))
        return self.focal / depth

    def faces_camera(self, center: Sequence[float], normal: Sequence[float]) -> bool:
        return float(np.dot(np.asarray(normal), self.eye - np.asarray(center))) > 0.0


def fit_camera(points: Iterable[Sequence[float]], *, target: Sequence[float], azimuth: float,
               elevation: float, fov: float = 30.0,
               rect: tuple[float, float, float, float] = (0.06, 0.16, 0.94, 0.80)) -> Camera:
    """Closest camera on this bearing that keeps every point inside *rect*.

    *rect* is ``(left, bottom, right, top)`` in figure fractions. Distance is
    solved by bisection, then the projection is re-centred on the rect so the
    subject does not hug one edge.
    """
    pts = np.asarray(list(points), dtype=float)
    left, bottom, right, top = rect
    box_w = (right - left) * theme.FRAME_W
    box_h = (top - bottom) * theme.FRAME_H

    def spans(distance: float) -> tuple[float, float, Camera]:
        cam = Camera(target, azimuth=azimuth, elevation=elevation, distance=distance, fov=fov)
        sx, sy, d = cam.project(pts)
        if (d <= 0.5).any():
            return float("inf"), float("inf"), cam
        return float(sx.max() - sx.min()), float(sy.max() - sy.min()), cam

    lo, hi = 2.0, 4000.0
    for _ in range(40):
        mid = (lo + hi) / 2
        w, h, _ = spans(mid)
        if w <= box_w and h <= box_h:
            hi = mid
        else:
            lo = mid
    _, _, cam = spans(hi)
    sx, sy, _ = cam.project(pts)
    want_x = (left + right) / 2 * theme.FRAME_W
    want_y = (bottom + top) / 2 * theme.FRAME_H
    shift_x = want_x - (sx.max() + sx.min()) / 2
    shift_y = want_y - (sy.max() + sy.min()) / 2
    center = ((cam.cx + shift_x) / theme.FRAME_W, (cam.cy + shift_y) / theme.FRAME_H)
    return Camera(target, azimuth=azimuth, elevation=elevation, distance=hi, fov=fov, center=center)


def pitch_corners(x_range: tuple[float, float] = (0.0, PITCH_X), height: float = 0.0) -> list[tuple[float, float, float]]:
    x_lo, x_hi = x_range
    pts = [(x_lo, 0, 0), (x_hi, 0, 0), (x_hi, PITCH_Y, 0), (x_lo, PITCH_Y, 0)]
    if height > 0:
        pts += [(x, y, height) for x, y, _ in pts]
    return pts


def stage(fig, *, zorder: float = 6.0):
    """Full-frame axes in output pixels. All 3D artists live here."""
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0], zorder=zorder)
    ax.set_xlim(0, theme.FRAME_W)
    ax.set_ylim(0, theme.FRAME_H)
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)
    return ax


def shade(color: str, normal: Sequence[float], *, ambient: float = 0.40) -> str:
    """Lambert shade of a flat face. Tops pick up a little sheen."""
    n = np.asarray(normal, dtype=float)
    n = n / (np.linalg.norm(n) or 1.0)
    lit = max(0.0, float(np.dot(n, _LIGHT)))
    if n[2] > 0.9:
        return theme.mix(color, "#ffffff", 0.10 + 0.08 * lit)
    return theme.mix("#000000", color, ambient + (1.0 - ambient) * lit)


def _rgba(color: str, alpha: float) -> tuple[float, float, float, float]:
    r, g, b, _ = to_rgba(color)
    return (r, g, b, max(0.0, min(1.0, float(alpha))))


class Painter:
    """Depth-sorted batch of shaded polygons, flushed as one collection."""

    def __init__(self, camera: Camera) -> None:
        self.camera = camera
        self._items: list[tuple[float, list[tuple[np.ndarray, Any, Any, float]]]] = []

    def __len__(self) -> int:
        return len(self._items)

    def _face(self, points3d: np.ndarray, face: str, alpha: float,
              edge: str | None, lw: float) -> tuple[np.ndarray, Any, Any, float]:
        sx, sy, _ = self.camera.project(points3d)
        verts = np.column_stack([sx, sy])
        edge_rgba = _rgba(edge, alpha) if edge else (0.0, 0.0, 0.0, 0.0)
        return verts, _rgba(face, alpha), edge_rgba, lw if edge else 0.0

    def polygon(self, points3d: Iterable[Sequence[float]], color: str, *, alpha: float = 1.0,
                edge: str | None = None, lw: float = 0.0, depth: float | None = None,
                lit: bool = False) -> None:
        pts = np.asarray(list(points3d), dtype=float)
        if len(pts) < 3 or alpha <= 0.01:
            return
        face = color
        if lit:
            normal = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            face = shade(color, normal)
        key = self.camera.depth_of(*pts.mean(axis=0)) if depth is None else depth
        self._items.append((key, [self._face(pts, face, alpha, edge, lw)]))

    def box(self, x0: float, y0: float, x1: float, y1: float, z0: float, z1: float,
            color: str, *, alpha: float = 1.0, edge: str | None = None, lw: float = 0.6,
            top: str | None = None, depth_bias: float = 0.0) -> None:
        """Axis-aligned prism. Only faces turned toward the camera are emitted."""
        if z1 - z0 <= 1e-4 or alpha <= 0.01:
            return
        cam = self.camera
        faces = (
            ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
            ((-1, 0, 0), [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)]),
            ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
            ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
            ((0, 1, 0), [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]),
        )
        emitted = []
        for normal, quad in faces:
            pts = np.asarray(quad, dtype=float)
            if not cam.faces_camera(pts.mean(axis=0), normal):
                continue
            face_color = (top or shade(color, normal)) if normal[2] > 0 else shade(color, normal)
            emitted.append((cam.depth_of(*pts.mean(axis=0)), self._face(pts, face_color, alpha, edge, lw)))
        if not emitted:
            return
        emitted.sort(key=lambda item: -item[0])
        key = cam.depth_of((x0 + x1) / 2, (y0 + y1) / 2, z0) + depth_bias
        self._items.append((key, [face for _, face in emitted]))

    def flush(self, ax, *, zorder: float = 10.0, antialiased: bool = True) -> None:
        if not self._items:
            return
        self._items.sort(key=lambda item: -item[0])
        verts, faces, edges, widths = [], [], [], []
        for _, polys in self._items:
            for poly, face, edge, lw in polys:
                verts.append(poly)
                faces.append(face)
                edges.append(edge)
                widths.append(lw)
        ax.add_collection(PolyCollection(
            verts, facecolors=faces, edgecolors=edges, linewidths=widths,
            antialiaseds=antialiased, zorder=zorder,
        ))
        self._items = []


def polyline(ax, camera: Camera, points3d: Iterable[Sequence[float]], color: str, *,
             lw: float = 1.4, alpha: float = 1.0, zorder: float = 8.0, glow: bool = False) -> None:
    pts = np.asarray(list(points3d), dtype=float)
    if len(pts) < 2 or alpha <= 0.01:
        return
    sx, sy, _ = camera.project(pts)
    if glow:
        for width, weight in ((lw * 4.2, 0.10), (lw * 2.4, 0.20)):
            ax.plot(sx, sy, color=color, lw=width, alpha=min(1.0, alpha * weight),
                    zorder=zorder - 0.1, solid_capstyle="round")
    ax.plot(sx, sy, color=color, lw=lw, alpha=min(1.0, alpha), zorder=zorder, solid_capstyle="round")


def segments(ax, camera: Camera, pairs: list[tuple[Sequence[float], Sequence[float]]], color: str, *,
             lw: float = 1.2, alpha: float = 1.0, zorder: float = 7.0) -> None:
    if not pairs or alpha <= 0.01:
        return
    starts = np.asarray([pair[0] for pair in pairs], dtype=float)
    ends = np.asarray([pair[1] for pair in pairs], dtype=float)
    sx0, sy0, _ = camera.project(starts)
    sx1, sy1, _ = camera.project(ends)
    lines = [((a, b), (c, d)) for a, b, c, d in zip(sx0, sy0, sx1, sy1)]
    ax.add_collection(LineCollection(lines, colors=[_rgba(color, alpha)], linewidths=lw, zorder=zorder))


def ground_circle(cx: float, cy: float, radius: float, *, z: float = 0.0,
                  start: float = 0.0, stop: float = math.tau, steps: int = 40) -> list[tuple[float, float, float]]:
    return [
        (cx + math.cos(angle) * radius, cy + math.sin(angle) * radius, z)
        for angle in np.linspace(start, stop, steps)
    ]


def ground_glow(ax, camera: Camera, x: float, y: float, color: str, *, radius: float = 3.0,
                alpha: float = 0.35, rings: int = 4, zorder: float = 6.5) -> None:
    """Soft light pool on the turf under a column or a goal."""
    if alpha <= 0.01:
        return
    polys, faces = [], []
    for index in range(rings, 0, -1):
        r = radius * index / rings
        sx, sy, _ = camera.project(ground_circle(x, y, r, z=0.02, steps=36))
        polys.append(np.column_stack([sx, sy]))
        faces.append(_rgba(color, alpha * (0.22 + 0.78 * (1 - index / rings)) / rings * 1.6))
    ax.add_collection(PolyCollection(polys, facecolors=faces, edgecolors="none", zorder=zorder))


def _stripe_colors(design: dict[str, Any]) -> tuple[str, str]:
    base = design.get("pitch") or theme.PITCH
    return theme.mix(base, "#1d2a22", 0.55), theme.mix(base, "#14201a", 0.40)


def draw_pitch(ax, camera: Camera, design: dict[str, Any], *, alpha: float = 1.0,
               x_range: tuple[float, float] = (0.0, PITCH_X), stripes: int = 14,
               line_alpha: float = 0.75, zorder: float = 4.0, goals: bool = True) -> None:
    """Striped turf, markings and goal frames, projected through *camera*."""
    if alpha <= 0.01:
        return
    x_lo, x_hi = x_range
    light, dark = _stripe_colors(design)
    polys, faces = [], []
    margin = 3.0
    apron = [(x_lo - margin, -margin, -0.01), (x_hi + margin, -margin, -0.01),
             (x_hi + margin, PITCH_Y + margin, -0.01), (x_lo - margin, PITCH_Y + margin, -0.01)]
    sx, sy, _ = camera.project(apron)
    polys.append(np.column_stack([sx, sy]))
    faces.append(_rgba("#070a08", alpha))
    width = PITCH_X / stripes
    for index in range(stripes):
        a, b = index * width, (index + 1) * width
        if b < x_lo or a > x_hi:
            continue
        a, b = max(a, x_lo), min(b, x_hi)
        quad = [(a, 0, 0), (b, 0, 0), (b, PITCH_Y, 0), (a, PITCH_Y, 0)]
        sx, sy, _ = camera.project(quad)
        polys.append(np.column_stack([sx, sy]))
        faces.append(_rgba(light if index % 2 == 0 else dark, alpha))
    ax.add_collection(PolyCollection(polys, facecolors=faces, edgecolors="none", zorder=zorder))

    line = design.get("pitch_line") or theme.PITCH_LINE
    line_color = theme.mix(line, "#ffffff", 0.18)
    la = alpha * line_alpha
    pairs: list[tuple[Sequence[float], Sequence[float]]] = []

    def seg(a, b):
        if (a[0] < x_lo - 0.01 and b[0] < x_lo - 0.01) or (a[0] > x_hi + 0.01 and b[0] > x_hi + 0.01):
            return
        pairs.append(((max(x_lo, min(x_hi, a[0])), a[1], 0.0), (max(x_lo, min(x_hi, b[0])), b[1], 0.0)))

    seg((0, 0), (PITCH_X, 0))
    seg((0, PITCH_Y), (PITCH_X, PITCH_Y))
    seg((0, 0), (0, PITCH_Y))
    seg((PITCH_X, 0), (PITCH_X, PITCH_Y))
    seg((PITCH_X / 2, 0), (PITCH_X / 2, PITCH_Y))
    box_w, six_w = 40.32 / 2, 18.32 / 2
    for end, sign in ((0.0, 1), (PITCH_X, -1)):
        bx, sxx = end + sign * 16.5, end + sign * 5.5
        seg((end, 34 - box_w), (bx, 34 - box_w))
        seg((bx, 34 - box_w), (bx, 34 + box_w))
        seg((bx, 34 + box_w), (end, 34 + box_w))
        seg((end, 34 - six_w), (sxx, 34 - six_w))
        seg((sxx, 34 - six_w), (sxx, 34 + six_w))
        seg((sxx, 34 + six_w), (end, 34 + six_w))
    segments(ax, camera, pairs, line_color, lw=1.3, alpha=la, zorder=zorder + 0.5)

    if x_lo <= PITCH_X / 2 <= x_hi:
        polyline(ax, camera, ground_circle(PITCH_X / 2, 34, 9.15, z=0.01, steps=64), line_color,
                 lw=1.3, alpha=la, zorder=zorder + 0.5)
    for end, sign in ((0.0, 1), (PITCH_X, -1)):
        spot = end + sign * 11.0
        if not (x_lo - 1 <= spot <= x_hi + 1):
            continue
        reach = math.acos(5.5 / 9.15)
        base = 0.0 if sign > 0 else math.pi
        arc = ground_circle(spot, 34, 9.15, z=0.01, start=base - reach, stop=base + reach, steps=24)
        polyline(ax, camera, arc, line_color, lw=1.3, alpha=la, zorder=zorder + 0.5)
        sx, sy = camera.point(spot, 34, 0.01)
        ax.scatter([sx], [sy], s=6, color=line_color, alpha=la, zorder=zorder + 0.6, linewidths=0)
    if goals:
        for end, sign in ((0.0, -1), (PITCH_X, 1)):
            if x_lo - 0.5 <= end <= x_hi + 0.5:
                draw_goal(ax, camera, end, sign, alpha=alpha, zorder=zorder + 2)


def draw_goal(ax, camera: Camera, x: float, outward: int, *, alpha: float = 1.0,
              zorder: float = 9.0, net: bool = True) -> None:
    """Posts, bar and a light net at goal line *x*; *outward* is +1 or -1."""
    if alpha <= 0.01:
        return
    left, right = 34 + GOAL_HALF_W, 34 - GOAL_HALF_W
    back = x + outward * GOAL_DEPTH
    if net:
        net_pairs = []
        for step in range(1, 9):
            yy = right + (left - right) * step / 9
            net_pairs.append(((back, yy, 0), (back, yy, GOAL_H * 0.82)))
            net_pairs.append(((x, yy, GOAL_H), (back, yy, GOAL_H * 0.82)))
        for step in range(1, 5):
            zz = GOAL_H * 0.82 * step / 5
            net_pairs.append(((back, right, zz), (back, left, zz)))
        segments(ax, camera, net_pairs, "#9aa59f", lw=0.6, alpha=0.30 * alpha, zorder=zorder - 0.2)
        frame = [((x, right, GOAL_H), (back, right, GOAL_H * 0.82)), ((x, left, GOAL_H), (back, left, GOAL_H * 0.82)),
                 ((back, right, 0), (back, right, GOAL_H * 0.82)), ((back, left, 0), (back, left, GOAL_H * 0.82))]
        segments(ax, camera, frame, "#b9c2bd", lw=0.9, alpha=0.45 * alpha, zorder=zorder - 0.1)
    post = [(x, right, 0), (x, right, GOAL_H), (x, left, GOAL_H), (x, left, 0)]
    polyline(ax, camera, post, theme.TEXT, lw=3.2, alpha=alpha, zorder=zorder, glow=True)


def ease_camera(progress: float, start: float, stop: float, *, ease=None) -> float:
    from .draw import ease_in_out

    curve = ease or ease_in_out
    return start + (stop - start) * curve(max(0.0, min(1.0, progress)))
