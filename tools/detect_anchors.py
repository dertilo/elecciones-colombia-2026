"""Detect E-14 page anchors on a rasterized PNG.

Anchors used for projection:

  * CORNER_TL/TR/BL/BR -- the four ~100x100 px solid black registration
    squares the Registraduria prints in each page corner.  Maximally
    spread (full-page extent), geometrically trivial -> robust under
    scan/photo distortion and the best basis for a 4-point perspective
    homography on phone scans.

Fallback / cross-check anchors (still emitted when found):

  * BARCODE    -- decoded payload + polygon (4 corners) via pyzbar.
  * HEADER_BAR -- the dark CANDIDATO|AGRUPACION|VOTACION horizontal band.

Output:
  templates/anchors/<stem>.json
  templates/anchors/<stem>_overlay.png
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    from pyzbar.pyzbar import decode as zbar_decode
except ImportError as e:
    raise SystemExit(
        "pyzbar not available; run with `uv run --with pyzbar --with opencv-python-headless --with numpy`"
    ) from e


@dataclass
class Anchor:
    name: str
    # Polygon: list of [x, y] vertices (4 for rectangular anchors).
    polygon: list[list[int]]
    # Convenience: bounding-box center.
    center: list[int]
    # Optional decoded payload (only for barcode).
    payload: str | None = None


def detect_barcode(gray: np.ndarray) -> Anchor | None:
    results = zbar_decode(gray)
    if not results:
        return None
    # Prefer the largest decoded barcode (in case pyzbar finds spurious ones).
    results.sort(key=lambda r: r.rect.width * r.rect.height, reverse=True)
    r = results[0]
    poly = [[int(p.x), int(p.y)] for p in r.polygon]
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cx = sum(xs) // len(xs)
    cy = sum(ys) // len(ys)
    return Anchor(
        name="barcode",
        polygon=poly,
        center=[cx, cy],
        payload=r.data.decode("utf-8", errors="replace"),
    )


def detect_header_bar(
    gray: np.ndarray,
    *,
    min_width_frac: float = 0.7,
    min_height_px: int = 80,
    max_height_px: int = 400,
    min_darkness: float = 0.55,  # mean ink fraction across the band
) -> Anchor | None:
    """Find the CANDIDATO|AGRUPACION|VOTACION dark horizontal bar.

    Strategy: per-row darkness profile (fraction of pixels below Otsu
    threshold) over the central horizontal stripe of the page; find the
    longest contiguous run of rows where darkness exceeds `min_darkness`;
    that's our bar.  Restrict the column range to ignore the barcode/page
    edges which can have high darkness too.
    """
    H, W = gray.shape
    # Limit to central 80% horizontally to ignore barcode + edge artifacts.
    col_lo = int(W * 0.10)
    col_hi = int(W * 0.90)
    strip = gray[:, col_lo:col_hi]
    # Otsu binarize, ink = 1.
    _, ink = cv2.threshold(strip, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    row_darkness = ink.mean(axis=1)  # 0..1 per row

    # Find contiguous runs above the threshold.
    above = row_darkness > min_darkness
    runs: list[tuple[int, int, float]] = []  # (y0, y1, mean_darkness)
    in_run = False
    y0 = 0
    for y in range(H):
        if above[y] and not in_run:
            y0 = y
            in_run = True
        elif not above[y] and in_run:
            runs.append((y0, y, float(row_darkness[y0:y].mean())))
            in_run = False
    if in_run:
        runs.append((y0, H, float(row_darkness[y0:H].mean())))

    # Filter by height.
    runs = [r for r in runs if min_height_px <= r[1] - r[0] <= max_height_px]
    if not runs:
        return None
    # Pick darkest.  In case of ties (rare), prefer earliest in the page.
    runs.sort(key=lambda r: (-r[2], r[0]))
    y0, y1, _ = runs[0]

    # Determine the bar's left/right edges by intersecting with content.
    band_ink = ink[y0:y1]
    col_ink = band_ink.mean(axis=0)
    above_cols = col_ink > 0.4
    if not above_cols.any():
        return None
    xs = np.where(above_cols)[0]
    x_left = int(xs[0] + col_lo)
    x_right = int(xs[-1] + col_lo)

    width = x_right - x_left
    if width < W * min_width_frac:
        return None

    poly = [[x_left, y0], [x_right, y0], [x_right, y1], [x_left, y1]]
    cx = (x_left + x_right) // 2
    cy = (y0 + y1) // 2
    return Anchor(name="header_bar", polygon=poly, center=[cx, cy])


CORNER_NAMES = ("corner_tl", "corner_tr", "corner_bl", "corner_br")


def detect_corner_squares(
    gray: np.ndarray,
    *,
    dark_thresh: int = 80,
    # Square side as fraction of page width.  Reference PNGs: ~100 px in
    # 3600 px wide -> ~2.8%.  Generous range absorbs perspective stretch
    # and lower-DPI phone photos.
    min_side_frac: float = 0.015,
    max_side_frac: float = 0.06,
    min_aspect: float = 0.4,
    max_aspect: float = 2.5,
    # Search-window size (fraction of page dim) per corner.  Has to be
    # wide enough to find the square even under heavy skew/rotation.
    win_frac_x: float = 0.20,
    win_frac_y: float = 0.10,
) -> list[Anchor]:
    """Find the four solid-black registration squares (one per corner).

    Returns up to 4 anchors named ``corner_tl``/``tr``/``bl``/``br``.
    Each anchor's polygon is the detected blob's axis-aligned bounding
    box; ``center`` is the connected-component centroid (sub-pixel before
    rounding to int).
    """
    H, W = gray.shape
    win_w = int(W * win_frac_x)
    win_h = int(H * win_frac_y)
    min_side = int(W * min_side_frac)
    max_side = int(W * max_side_frac)
    # Square area in pixels: a blob of side s has area s^2 (roughly).
    min_area = (min_side * min_side) // 2  # allow for clipped corners
    max_area = max_side * max_side * 2

    # Each window is (y0, y1, x0, x1) plus a "corner point" used for the
    # distance score: the printed registration square is always the
    # outermost dark blob in its corner, so we pick the candidate whose
    # centroid lies closest to the page corner.  This naturally rejects
    # the QR-finder patterns, page-number text, etc. that sit further in.
    windows: dict[str, tuple[int, int, int, int, int, int]] = {
        "corner_tl": (0,         win_h,     0,         win_w,     0, 0),
        "corner_tr": (0,         win_h,     W - win_w, W,         W, 0),
        "corner_bl": (H - win_h, H,         0,         win_w,     0, H),
        "corner_br": (H - win_h, H,         W - win_w, W,         W, H),
    }

    anchors: list[Anchor] = []
    for name, (y0, y1, x0, x1, corner_x, corner_y) in windows.items():
        sub = gray[y0:y1, x0:x1]
        _, bw = cv2.threshold(sub, dark_thresh, 255, cv2.THRESH_BINARY_INV)
        n, _, stats, cents = cv2.connectedComponentsWithStats(bw, 8)
        best: tuple[float, tuple[int, int, int, int, float, float]] | None = None
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if a < min_area or a > max_area:
                continue
            if not (min_side <= max(w, h) <= max_side):
                continue
            if h == 0:
                continue
            ar = w / h
            if not (min_aspect <= ar <= max_aspect):
                continue
            # OpenCV centroids are (x, y).
            cx_loc, cy_loc = cents[i]
            gx_c = x0 + cx_loc
            gy_c = y0 + cy_loc
            # Score: distance to corner.  Lower is better.
            dx = gx_c - corner_x
            dy = gy_c - corner_y
            dist = (dx * dx + dy * dy) ** 0.5
            if best is None or dist < best[0]:
                best = (dist, (int(x), int(y), int(w), int(h), float(cx_loc), float(cy_loc)))
        if best is None:
            continue
        _, (bx, by, bw, bh, cx_loc, cy_loc) = best
        gx, gy = x0 + bx, y0 + by
        poly = [
            [gx,        gy],
            [gx + bw,   gy],
            [gx + bw,   gy + bh],
            [gx,        gy + bh],
        ]
        anchors.append(
            Anchor(
                name=name,
                polygon=poly,
                center=[int(round(x0 + cx_loc)), int(round(y0 + cy_loc))],
            )
        )
    return anchors


def detect_anchors(img_path: Path) -> tuple[list[Anchor], np.ndarray]:
    gray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(img_path)

    anchors: list[Anchor] = []
    anchors.extend(detect_corner_squares(gray))
    if (a := detect_barcode(gray)) is not None:
        anchors.append(a)
    if (a := detect_header_bar(gray)) is not None:
        anchors.append(a)

    debug = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    colors = {
        "barcode": (0, 200, 0),       # green
        "header_bar": (255, 0, 255),  # magenta
        "corner_tl": (0, 0, 255),     # red
        "corner_tr": (0, 0, 255),
        "corner_bl": (0, 0, 255),
        "corner_br": (0, 0, 255),
        "mesa_line": (0, 200, 255),   # orange (reserved)
        "kit_footer": (255, 200, 0),  # cyan   (reserved)
    }
    for a in anchors:
        c = colors.get(a.name, (0, 0, 255))
        pts = np.array(a.polygon, dtype=np.int32)
        cv2.polylines(debug, [pts], isClosed=True, color=c, thickness=6)
        cv2.circle(debug, tuple(a.center), 18, c, -1)
        label = a.name + (f" [{a.payload}]" if a.payload else "")
        cv2.putText(debug, label, (a.center[0] + 24, a.center[1] - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, c, 3)

    return anchors, debug


def main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <reference.png> [...]", file=sys.stderr)
        sys.exit(2)
    out_dir = Path("templates/anchors")
    out_dir.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        path = Path(arg)
        anchors, debug = detect_anchors(path)
        stem = path.stem
        payload = {
            "source": str(path),
            "shape": list(debug.shape[:2]),
            "anchors": [asdict(a) for a in anchors],
        }
        (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2))
        cv2.imwrite(str(out_dir / f"{stem}_overlay.png"), debug)
        names = ", ".join(a.name for a in anchors) or "none"
        print(f"{stem}: {len(anchors)} anchors ({names})")


if __name__ == "__main__":
    main()
