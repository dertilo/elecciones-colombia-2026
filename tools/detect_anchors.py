"""Detect E-14 page anchors on a rasterized PNG.

Phase-1 anchors (most robust, available on every candidate-rows page):

  * BARCODE      -- decoded payload + polygon (4 corners) via pyzbar.
  * HEADER_BAR   -- the dark CANDIDATO|AGRUPACION|VOTACION horizontal band.

These two give us a similarity transform (translation + rotation + scale).
Adding 2 more (mesa-code line, KIT footer) -> full perspective homography
for the phone-photo subset.  Those come in a follow-up pass.

Output:
  data_2026/templates/anchors/<stem>.json
  data_2026/templates/anchors/<stem>_overlay.png
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


def detect_anchors(img_path: Path) -> tuple[list[Anchor], np.ndarray]:
    gray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(img_path)

    anchors: list[Anchor] = []
    if (a := detect_barcode(gray)) is not None:
        anchors.append(a)
    if (a := detect_header_bar(gray)) is not None:
        anchors.append(a)

    debug = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    colors = {
        "barcode": (0, 200, 0),       # green
        "header_bar": (255, 0, 255),  # magenta
        "mesa_line": (0, 200, 255),   # orange
        "kit_footer": (255, 200, 0),  # cyan
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
    out_dir = Path("data_2026/templates/anchors")
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
