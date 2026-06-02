"""
Contour-snap refinement of schema-projected cells.

For each bordered cell (candidate_row, nivelacion_row, summary_row,
signature_block, vote_digit), we look for the actual rectangle borders
in a small halo around the projected position and snap the box to them.
This corrects small per-page registration drift (a few to a few-tens of px)
that the absolute-pixel schema can't capture on its own.

Algorithm (per reference image):
  Pass 1 — snap row-type and signature rectangles with halo=50:
    * top    = strongest horizontal ink line in [y-h, y+h]
    * bottom = strongest horizontal ink line in [y+H-h, y+H+h]
    * left   = strongest vertical   ink line in [x-h, x+h] over [top..bottom]
    * right  = strongest vertical   ink line in [x+W-h, x+W+h] over [top..bottom]
  Pass 2 — for each vote_digit cell:
    * translate by the parent row's left-edge dx and vertical-center dy
      (dx propagation matters for the consulado template, whose table is
      printed ~33 px left of the schema's nominal DIGIT_X0; without it
      halo=20 can't recover and digits stick to the projected x)
    * snap each border with halo=20

If a border is not found (coverage below threshold), we keep the projected
coord for that side.

Limitations / gotchas:
  * The ±50 px halo bounds how far the schema can be wrong before refinement
    silently degrades. If the projected position is off by >halo, the search
    either snaps to a neighbouring (wrong) line or falls back to the projected
    coord — both look subtly mis-aligned in the overlay rather than failing
    loudly. Symptom seen on r1/c1 nivelacion before fix: when the schema
    assumed uniform row pitch but real rows were non-uniform (row 1 ~360 px,
    row 2 ~265 px, row 3 ~325 px — row 1 tallest because its label
    'TOTAL VOTANTES FORMULARIO E-11' wraps to two lines), bottoms of niv_2
    and niv_3 fell outside the halo and refinement could not recover.
    Fix: encode the actual per-row (y0, h) tuples in e14_schema.py rather
    than computing them from a single pitch.
  * Otsu thresholding makes the dark colored 'NIVELACIÓN DE LA MESA' /
    'CANDIDATO ...' header bars count as ink. A naive 'strongest cov=1.00
    horizontal line in this band' search will pick a row *inside* the
    colored bar (where the bar background is solid) rather than the
    actual table border that sits at the bar's bottom edge. When measuring
    new schema coordinates by ink coverage, exclude or visually verify
    rows that fall inside known dark bands.

Outputs:
  templates/projected/<stem>_refined_overlay.png
  templates/projected/<stem>_refined.json

Usage:
  uv run --with opencv-python-headless --with numpy \\
    python tools/refine_contours.py \\
    regular-1 regular-2 regular-3 consulado-1 consulado-2 consulado-3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "tools"))
from e14_schema import Cell, cells, reference_image           # noqa: E402
from project_schema import draw_overlay, cells_to_json        # noqa: E402


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

ROW_HALO        = 50   # search radius for row/signature borders
DIGIT_HALO      = 20   # search radius for vote-digit borders
MIN_COVERAGE    = 0.70 # ink fraction required to accept a border line

# Cell kinds that have a continuous rectangle border to snap to.
_ROW_KINDS = {"candidate_row", "nivelacion_row", "summary_row", "signature_block"}


# ---------------------------------------------------------------------------
# Ink + line detection
# ---------------------------------------------------------------------------

def _ink_mask(gray: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _find_h_line(ink: np.ndarray, x_lo: int, x_hi: int,
                 y_center: int, halo: int,
                 min_cov: float = MIN_COVERAGE) -> int | None:
    """Strongest horizontal line in [y_center±halo] spanning [x_lo, x_hi]."""
    H, W = ink.shape
    y0 = max(0, y_center - halo)
    y1 = min(H, y_center + halo + 1)
    x_lo = max(0, x_lo); x_hi = min(W, x_hi)
    if y1 <= y0 or x_hi <= x_lo:
        return None
    cov = ink[y0:y1, x_lo:x_hi].mean(axis=1)
    peak = int(np.argmax(cov))
    return y0 + peak if cov[peak] >= min_cov else None


def _find_v_line(ink: np.ndarray, y_lo: int, y_hi: int,
                 x_center: int, halo: int,
                 min_cov: float = MIN_COVERAGE) -> int | None:
    """Strongest vertical line in [x_center±halo] spanning [y_lo, y_hi]."""
    H, W = ink.shape
    x0 = max(0, x_center - halo)
    x1 = min(W, x_center + halo + 1)
    y_lo = max(0, y_lo); y_hi = min(H, y_hi)
    if x1 <= x0 or y_hi <= y_lo:
        return None
    cov = ink[y_lo:y_hi, x0:x1].mean(axis=0)
    peak = int(np.argmax(cov))
    return x0 + peak if cov[peak] >= min_cov else None


def _snap_rect(ink: np.ndarray, bbox: tuple[int, int, int, int],
               halo: int) -> tuple[int, int, int, int]:
    """Snap (x,y,w,h) to the nearest strong rectangle borders."""
    x, y, w, h = bbox
    y_top    = _find_h_line(ink, x,     x + w, y,     halo)
    y_bottom = _find_h_line(ink, x,     x + w, y + h, halo)

    yt = y_top    if y_top    is not None else y
    yb = y_bottom if y_bottom is not None else y + h

    x_left  = _find_v_line(ink, yt, yb, x,     halo)
    x_right = _find_v_line(ink, yt, yb, x + w, halo)

    xl = x_left  if x_left  is not None else x
    xr = x_right if x_right is not None else x + w
    return (xl, yt, xr - xl, yb - yt)


# ---------------------------------------------------------------------------
# Refinement
# ---------------------------------------------------------------------------

def refine(ref_gray: np.ndarray, cell_list: list[Cell]) -> tuple[list[Cell], dict]:
    """Return refined cell list + small stats dict."""
    ink = _ink_mask(ref_gray)

    by_id = {c.id: c for c in cell_list}

    # Pass 1: snap row-type + signature rectangles
    new_bbox: dict[str, tuple[int, int, int, int]] = {}
    for c in cell_list:
        if c.kind in _ROW_KINDS:
            new_bbox[c.id] = _snap_rect(ink, c.bbox, ROW_HALO)

    # Pass 2: digit cells — shift by parent row, then snap with small halo
    snapped_digits = 0
    for c in cell_list:
        if c.kind != "vote_digit":
            continue
        parent_id = c.id.rsplit(".", 1)[0]
        bx, by, bw, bh = c.bbox
        if parent_id in new_bbox and parent_id in by_id:
            ox, oy, ow, oh = by_id[parent_id].bbox
            nx, ny, nw, nh = new_bbox[parent_id]
            # Translate digits by the parent row's left-edge shift (dx) and
            # vertical-center shift (dy). Some templates (consulado) have the
            # whole table printed shifted left by ~30 px relative to the
            # schema's nominal CAND_X / DIGIT_X0; without dx propagation the
            # digit halo (20 px) is too small to recover.
            dx = nx - ox
            dy = (ny + nh // 2) - (oy + oh // 2)
            shifted = (bx + dx, by + dy, bw, bh)
        else:
            shifted = (bx, by, bw, bh)
        new_bbox[c.id] = _snap_rect(ink, shifted, DIGIT_HALO)
        snapped_digits += 1

    # Compose output preserving original order
    refined: list[Cell] = []
    for c in cell_list:
        if c.id in new_bbox:
            refined.append(Cell(c.id, c.kind, new_bbox[c.id]))
        else:
            refined.append(c)

    # Stats: median absolute drift per kind (useful for diagnostics)
    drifts: dict[str, list[int]] = {}
    for c, r in zip(cell_list, refined):
        if c.bbox == r.bbox:
            continue
        ox, oy, _, _ = c.bbox
        rx, ry, _, _ = r.bbox
        drifts.setdefault(c.kind, []).append(abs(ry - oy) + abs(rx - ox))
    stats = {k: {"n": len(v), "median_drift_px": int(np.median(v))}
             for k, v in drifts.items()}
    stats["digits_snapped"] = snapped_digits

    return refined, stats


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def process_stem(stem: str, out_dir: Path) -> None:
    template, page_str = stem.rsplit("-", 1)
    page = int(page_str)

    ref_path = reference_image(template, page)
    if not ref_path.exists():
        print(f"  [SKIP] reference image not found: {ref_path}", file=sys.stderr)
        return

    img = cv2.imread(str(ref_path))
    if img is None:
        print(f"  [ERROR] failed to read: {ref_path}", file=sys.stderr)
        return
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    projected = cells(template, page)
    refined, stats = refine(gray, projected)

    overlay = draw_overlay(img, refined)
    overlay_path = out_dir / f"{stem}_refined_overlay.png"
    json_path    = out_dir / f"{stem}_refined.json"
    cv2.imwrite(str(overlay_path), overlay)
    with json_path.open("w") as f:
        json.dump(cells_to_json(refined), f, indent=2)

    print(f"  {stem}: {len(refined)} cells; stats={stats}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contour-snap refinement of E-14 projected cells"
    )
    parser.add_argument(
        "stems", nargs="+",
        help="One or more <template>-<page> keys, e.g. regular-1 consulado-2"
    )
    args = parser.parse_args()

    out_dir = _REPO / "templates" / "projected"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem in args.stems:
        process_stem(stem, out_dir)
    print("Done.")


if __name__ == "__main__":
    main()
