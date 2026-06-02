"""
Project the E-14 cell schema onto reference PNGs and produce:
  - data_2026/templates/projected/<stem>_overlay.png  (full-res colour overlay)
  - data_2026/templates/projected/<stem>.json          (cell list as JSON)

Usage:
  uv run --with opencv-python-headless --with numpy \\
    python tools/project_schema.py \\
    regular-1 regular-2 regular-3 consulado-1 consulado-2 consulado-3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# ── locate repo root regardless of cwd ──────────────────────────────────────
_REPO = Path(__file__).parent.parent

sys.path.insert(0, str(_REPO / "tools"))
from e14_schema import cells, reference_image  # noqa: E402 (after sys.path)

# ---------------------------------------------------------------------------
# Colour palette  (BGR for OpenCV)
# ---------------------------------------------------------------------------

PALETTE: dict[str, tuple[int, int, int]] = {
    "vote_digit":      (0,   0,   220),   # red
    "candidate_row":   (0,   200,  0),    # green
    "nivelacion_row":  (200, 200,  0),    # cyan-ish
    "summary_row":     (0,   165, 255),   # orange
    "signature_block": (255,   0, 255),   # magenta
    "bar":             (0,   220, 220),   # yellow
    "mesa_info_band":  (180, 180, 180),   # light grey
    "mesa_code_line":  (180, 180, 180),
    "header_band":     (180, 180, 180),
    "footer":          (180, 180, 180),
    "checkbox":        (255,   0,   0),   # blue
}

# Thickness per kind (thicker outline for container rows, thin for digit cells)
THICKNESS: dict[str, int] = {
    "vote_digit":      2,
    "candidate_row":   4,
    "nivelacion_row":  4,
    "summary_row":     4,
    "signature_block": 4,
    "bar":             3,
    "mesa_info_band":  2,
    "mesa_code_line":  2,
    "header_band":     2,
    "footer":          2,
    "checkbox":        2,
}

# Draw order: container kinds first, overlaid by digit cells
DRAW_ORDER = [
    "header_band", "mesa_info_band", "mesa_code_line", "footer",
    "bar",
    "nivelacion_row", "candidate_row", "summary_row",
    "signature_block",
    "checkbox",
    "vote_digit",
]


def draw_overlay(img: np.ndarray, cell_list) -> np.ndarray:
    overlay = img.copy()
    by_kind: dict[str, list] = {}
    for c in cell_list:
        by_kind.setdefault(c.kind, []).append(c)

    for kind in DRAW_ORDER:
        if kind not in by_kind:
            continue
        colour = PALETTE.get(kind, (200, 200, 200))
        thickness = THICKNESS.get(kind, 2)
        for c in by_kind[kind]:
            x, y, w, h = c.bbox
            cv2.rectangle(overlay, (x, y), (x + w, y + h), colour, thickness)
            # Label: small text at top-left of cell (skip tiny digit cells)
            if kind not in ("vote_digit",):
                label = c.id.split(".")[-1]   # last segment only
                cv2.putText(
                    overlay, label,
                    (x + 4, y + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2,
                    cv2.LINE_AA
                )

    # Also label digits compactly
    for c in by_kind.get("vote_digit", []):
        x, y, w, h = c.bbox
        label = c.id.split(".")[-1]   # e.g. "digit_1"
        cv2.putText(
            overlay, label,
            (x + 2, y + 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
            PALETTE["vote_digit"], 1, cv2.LINE_AA
        )

    return overlay


def cells_to_json(cell_list) -> list[dict]:
    return [
        {"id": c.id, "kind": c.kind,
         "x": c.bbox[0], "y": c.bbox[1],
         "w": c.bbox[2], "h": c.bbox[3]}
        for c in cell_list
    ]


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

    cell_list = cells(template, page)
    overlay = draw_overlay(img, cell_list)

    overlay_path = out_dir / f"{stem}_overlay.png"
    json_path    = out_dir / f"{stem}.json"

    cv2.imwrite(str(overlay_path), overlay)

    with json_path.open("w") as f:
        json.dump(cells_to_json(cell_list), f, indent=2)

    print(f"  {stem}: {len(cell_list)} cells → {overlay_path.name}, {json_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Project E-14 cell schema onto reference PNGs")
    parser.add_argument(
        "stems", nargs="+",
        help="One or more <template>-<page> keys, e.g. regular-1 consulado-2"
    )
    args = parser.parse_args()

    out_dir = _REPO / "data_2026" / "templates" / "projected"
    out_dir.mkdir(parents=True, exist_ok=True)

    for stem in args.stems:
        process_stem(stem, out_dir)

    print("Done.")


if __name__ == "__main__":
    main()
