"""
E-14 form cell schema — declarative layout in reference-image pixel coords.

Reference images live at:
  templates/ref/<template>-<page>.png
All are 3600 px wide; heights vary (see SIZE_MAP).

All bboxes are (x, y, w, h) in reference-image pixel coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    id: str
    kind: str   # see PALETTE in project_schema.py for valid kinds
    bbox: tuple[int, int, int, int]   # (x, y, w, h) reference pixels


# ---------------------------------------------------------------------------
# Reference-image dimensions (measured)
# ---------------------------------------------------------------------------

SIZE_MAP: dict[tuple[str, int], tuple[int, int]] = {
    ("regular",   1): (3600, 10825),
    ("regular",   2): (3600, 10834),
    ("regular",   3): (3600, 10834),
    ("consulado", 1): (3600, 10892),
    ("consulado", 2): (3600, 10867),
    ("consulado", 3): (3600, 10900),
}

# Horizontal page margins (same for all pages)
X_LEFT  = 110
X_RIGHT = 3490
PAGE_W  = X_RIGHT - X_LEFT   # ≈ 3380

# Candidate-row rounded-rectangle horizontal span
CAND_X  = 200
CAND_W  = 3215   # x=[200,3415]

# Vote-digit geometry (right side of each numeric row)
DIGIT_X0     = 2500   # left edge of first digit cell
DIGIT_WIDTH  = 270
DIGIT_STRIDE = 300    # center-to-center = DIGIT_WIDTH + gap(30)
DIGIT_HEIGHT_FRAC = 0.55   # fraction of row height


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(bar_id: str, y0: int, y1: int) -> Cell:
    """Horizontal section-header bar spanning full page width."""
    return Cell(bar_id, "bar", (X_LEFT, y0, PAGE_W, y1 - y0))


def _footer(page_id: str, y0: int, y1: int) -> Cell:
    return Cell(f"{page_id}.footer", "footer", (X_LEFT, y0, PAGE_W, y1 - y0))


def _mesa_info_band(page_id: str, y0: int, y1: int) -> Cell:
    return Cell(f"{page_id}.mesa_info_band", "mesa_info_band",
                (X_LEFT, y0, PAGE_W, y1 - y0))


def _header_band(page_id: str, y0: int, y1: int) -> Cell:
    return Cell(f"{page_id}.header_band", "header_band",
                (X_LEFT, y0, PAGE_W, y1 - y0))


def _digits(row_id: str, y_center: int, row_height: int) -> list[Cell]:
    """Three vote-digit cells for one numeric row."""
    h = int(row_height * DIGIT_HEIGHT_FRAC)
    y = y_center - h // 2
    return [
        Cell(f"{row_id}.digit_{i + 1}", "vote_digit",
             (DIGIT_X0 + i * DIGIT_STRIDE, y, DIGIT_WIDTH, h))
        for i in range(3)
    ]


def _candidate_row(row_id: str, cand_no: int,
                   y0: int, row_h: int) -> list[Cell]:
    """One candidate row (outline) + 3 digit sub-cells."""
    y_center = y0 + row_h // 2
    row_cell = Cell(row_id, "candidate_row", (CAND_X, y0, CAND_W, row_h))
    return [row_cell] + _digits(row_id, y_center, row_h)


def _niv_row(row_id: str, y0: int, row_h: int) -> list[Cell]:
    """One nivelación row (outline) + 3 digit sub-cells."""
    y_center = y0 + row_h // 2
    row_cell = Cell(row_id, "nivelacion_row", (CAND_X, y0, CAND_W, row_h))
    return [row_cell] + _digits(row_id, y_center, row_h)


def _summary_row(row_id: str, y0: int, row_h: int) -> list[Cell]:
    """One summary/totals row (outline) + 3 digit sub-cells."""
    y_center = y0 + row_h // 2
    row_cell = Cell(row_id, "summary_row", (CAND_X, y0, CAND_W, row_h))
    return [row_cell] + _digits(row_id, y_center, row_h)


def _sig_rows(page_id: str,
              row_specs: list[tuple[int, int]],
              col_specs: list[tuple[int, int]]) -> list[Cell]:
    """Signature blocks laid out by explicit (y0, h) rows × (x0, w) columns."""
    cells: list[Cell] = []
    for r, (y0, rh) in enumerate(row_specs):
        for c, (x0, cw) in enumerate(col_specs):
            cells.append(Cell(
                f"{page_id}.sig_{r * len(col_specs) + c + 1}",
                "signature_block",
                (x0, y0, cw, rh),
            ))
    return cells


# ---------------------------------------------------------------------------
# Per-page layout functions
# ---------------------------------------------------------------------------

def _regular_1() -> list[Cell]:
    pid = "r1"
    h = SIZE_MAP[("regular", 1)][1]   # 10825
    out: list[Cell] = []

    # Header / mesa info (top ~8% of page)
    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2429))

    # NIVELACIÓN section bar + 3 rows.
    # Bar 2429..2596 (dark colored band, label inside it).
    # Niv block below: top=2596, dividers=2916 & 3183, bottom=3512.
    # Rows are NOT uniform — row 1 ("TOTAL VOTANTES FORMULARIO E-11") wraps to
    # two lines, so it's taller than rows 2 & 3.
    out.append(_bar("r1.bar_nivelacion", 2429, 2596))
    niv_rows_r1 = [(2596, 320), (2916, 267), (3183, 329)]
    for i, (y0, rh) in enumerate(niv_rows_r1):
        out += _niv_row(f"r1.niv_{i + 1}", y0, rh)

    # CANDIDATO section bar
    out.append(_bar("r1.bar_candidato", 3671, 3837))

    # 7 candidate rows
    cand_tops_r1 = [3900, 4821, 5754, 6679, 7609, 8538, 9459]
    cand_h = 850
    for i, y0 in enumerate(cand_tops_r1):
        out += _candidate_row(f"r1.cand_{i + 1}", i + 1, y0, cand_h)

    # Footer
    out.append(_footer(pid, 10300, h))

    return out


def _regular_2() -> list[Cell]:
    pid = "r2"
    h = SIZE_MAP[("regular", 2)][1]   # 10834
    out: list[Cell] = []

    # Header / mesa info
    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2441))

    # CANDIDATO section bar (page 2 has no NIVELACIÓN)
    out.append(_bar("r2.bar_candidato", 2441, 2600))

    # 6 candidate rows (candidates 8..13)
    cand_tops_r2 = [2662, 3591, 4521, 5446, 6375, 7300]
    cand_h = 850
    for i, y0 in enumerate(cand_tops_r2):
        out += _candidate_row(f"r2.cand_{i + 8}", i + 8, y0, cand_h)

    # Summary / totals rows (4 rows below candidates)
    # Measured: rectangle boundaries at y=8296, 8625, 8883, 9150, 9475.
    # Row 1 (VOTOS EN BLANCO)   is taller because there's a label-header strip on top;
    # Row 4 (SUMA TOTAL …)      is taller because its label spans 2 text lines.
    sum_rows_r2 = [(8296, 329), (8625, 258), (8883, 267), (9150, 325)]
    for i, (y0, rh) in enumerate(sum_rows_r2):
        out += _summary_row(f"r2.sum_{i + 1}", y0, rh)

    # Footer
    out.append(_footer(pid, 9700, h))

    return out


def _regular_3() -> list[Cell]:
    pid = "r3"
    h = SIZE_MAP[("regular", 3)][1]   # 10834
    out: list[Cell] = []

    # Header / mesa info
    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2441))

    # CONSTANCIAS bar
    out.append(_bar("r3.bar_constancias", 2441, 2587))

    # Signature blocks: 2×3 grid in the lower half of the page.
    # Measured from rectangle borders: row tops 8087, 8921, 9663;
    # column verticals at x=212, 1813, 3421.
    # (Upper area y=2587..8087 still TODO: ¿HUBO RECUENTO? checkbox,
    # SOLICITADO POR, EN REPRESENTACIÓN DE — not yet declared.)
    out += _sig_rows(
        pid,
        row_specs=[(8087, 796), (8921, 704), (9663, 700)],
        col_specs=[(212, 1601), (1813, 1608)],
    )

    # Footer
    out.append(_footer(pid, 10350, h))

    return out


def _consulado_1() -> list[Cell]:
    pid = "c1"
    h = SIZE_MAP[("consulado", 1)][1]   # 10892
    out: list[Cell] = []

    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2462))

    # NIVELACIÓN bar + 3 rows.
    # Bar 2462..2633 (dark colored band, label inside it).
    # Niv block below: top=2633, dividers=2950 & 3216, bottom=3541.
    # Same shape as r1: row 1 is taller because its label wraps to 2 lines.
    out.append(_bar("c1.bar_nivelacion", 2462, 2633))
    niv_rows_c1 = [(2633, 317), (2950, 266), (3216, 325)]
    for i, (y0, rh) in enumerate(niv_rows_c1):
        out += _niv_row(f"c1.niv_{i + 1}", y0, rh)

    # CANDIDATO bar
    out.append(_bar("c1.bar_candidato", 3708, 3866))

    # 7 candidate rows
    cand_tops_c1 = [3929, 4854, 5779, 6712, 7637, 8566, 9483]
    cand_h = 850
    for i, y0 in enumerate(cand_tops_c1):
        out += _candidate_row(f"c1.cand_{i + 1}", i + 1, y0, cand_h)

    # Footer
    out.append(_footer(pid, 10330, h))

    return out


def _consulado_2() -> list[Cell]:
    pid = "c2"
    h = SIZE_MAP[("consulado", 2)][1]   # 10867
    out: list[Cell] = []

    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2458))

    # CANDIDATO bar
    out.append(_bar("c2.bar_candidato", 2458, 2616))

    # 6 candidate rows (candidates 8..13)
    cand_tops_c2 = [2679, 3608, 4537, 5462, 6391, 7316]
    cand_h = 850
    for i, y0 in enumerate(cand_tops_c2):
        out += _candidate_row(f"c2.cand_{i + 8}", i + 8, y0, cand_h)

    # Summary / totals rows (4 rows below candidates) — measured from
    # rectangle boundaries at y=8312, 8641, 8900, 9162, 9487.
    sum_rows_c2 = [(8312, 329), (8641, 259), (8900, 262), (9162, 325)]
    for i, (y0, rh) in enumerate(sum_rows_c2):
        out += _summary_row(f"c2.sum_{i + 1}", y0, rh)

    # Footer
    out.append(_footer(pid, 9700, h))

    return out


def _consulado_3() -> list[Cell]:
    pid = "c3"
    h = SIZE_MAP[("consulado", 3)][1]   # 10900
    out: list[Cell] = []

    out.append(_header_band(pid, 0, 400))
    out.append(_mesa_info_band(pid, 400, 2462))

    # CONSTANCIAS bar
    out.append(_bar("c3.bar_constancias", 2462, 2608))

    # Signature blocks: 2×2 grid in the lower half of the page.
    # Measured from rectangle borders: row tops 8842, 9680;
    # column verticals at x=162, 1767, 3375.
    # (Upper area y=2608..8842 still TODO: ¿HUBO RECUENTO? checkbox,
    # SOLICITADO POR, EN REPRESENTACIÓN DE — not yet declared.)
    out += _sig_rows(
        pid,
        row_specs=[(8842, 796), (9680, 695)],
        col_specs=[(162, 1605), (1767, 1608)],
    )

    # Footer
    out.append(_footer(pid, 10375, h))

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DISPATCH: dict[tuple[str, int], callable] = {
    ("regular",   1): _regular_1,
    ("regular",   2): _regular_2,
    ("regular",   3): _regular_3,
    ("consulado", 1): _consulado_1,
    ("consulado", 2): _consulado_2,
    ("consulado", 3): _consulado_3,
}

_REF_DIR = Path(__file__).parent.parent / "templates" / "ref"


def cells(template: str, page: int) -> list[Cell]:
    """Return the declared cell list for (template, page)."""
    key = (template, page)
    if key not in _DISPATCH:
        raise ValueError(f"Unknown (template, page) combination: {key!r}")
    return _DISPATCH[key]()


def reference_image(template: str, page: int) -> Path:
    """Return the path to the reference PNG for (template, page)."""
    return _REF_DIR / f"{template}-{page}.png"
