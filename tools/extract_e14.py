#!/usr/bin/env python3
"""Per-PDF E-14 extraction pipeline.

End-to-end: PDF -> per-cell PNG crops + sidecar JSON, in the reference
frame.  Chains the existing pieces:

    rasterize (pdftoppm @ 300 DPI)
        -> detect_anchors        (tools/detect_anchors.py)
        -> warp_to_reference     (tools/warp_to_reference.py)
        -> apply e14_schema.cells(template, page)
        -> crop each cell from the warped image
        -> write <cell_id>.png + page.json + extraction.json

Layout:

    <out>/<mesa_id>/
      extraction.json               # top-level: per-page status summary
      page-<n>/
        page.json                   # warp meta + cell bboxes + filenames
        cells/<cell_id>.png         # one PNG per cell (warped-frame crops)

``mesa_id`` is the 12-digit ``dep+mun+zon+sub+mesa`` parsed from the
corpus path (e.g. ``data_2026/e14/delegados/05/006/099/40/001_*.pdf``
-> ``050060994001``).  PDFs outside the corpus layout need
``--mesa-id`` and ``--template`` explicitly.

Failures (insufficient anchors, missing schema, raster errors) are
recorded as status strings in the JSON; they do not crash the run.
The warped full-page PNG is *not* written by default -- it is ~10 MB
per page, and a full corpus sweep would cost ~3.6 TB.  Use
``--save-warped`` if you need it for debugging.

Usage:

    uv run --with pyzbar --with opencv-python-headless --with numpy \\
        python tools/extract_e14.py path/to/foo.pdf [more.pdf ...] \\
        --out /tmp/e14-extract
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import cv2

_TOOLS = Path(__file__).parent
sys.path.insert(0, str(_TOOLS))

from e14_schema import Cell, cells as schema_cells  # noqa: E402
from warp_to_reference import warp_one  # noqa: E402


PATH_RE = re.compile(
    r".*/delegados/(?P<dep>\d{2})/(?P<mun>\d{3})/(?P<zon>\d{3})/"
    r"(?P<sub>\d{2})/(?P<mesa>\d{3})_[0-9a-f]+\.pdf$"
)


def _template_for_dep(dep: str) -> str:
    return "consulado" if dep == "88" else "regular"


def _parse_corpus_path(pdf: Path) -> Optional[tuple[str, str]]:
    """Return (mesa_id, template) from a corpus-style path, or None."""
    m = PATH_RE.match(str(pdf))
    if not m:
        return None
    mesa_id = f"{m['dep']}{m['mun']}{m['zon']}{m['sub']}{m['mesa']}"
    return mesa_id, _template_for_dep(m["dep"])


def _rasterize(pdf: Path, scratch: Path, dpi: int) -> list[Path]:
    """pdftoppm -> list of generated PNG paths in scratch/."""
    prefix = scratch / "page"
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)],
        check=True,
        capture_output=True,
    )
    return sorted(scratch.glob("page-*.png"))


def _crop_cell(warped: "cv2.Mat", bbox: tuple[int, int, int, int]) -> "cv2.Mat":
    """Crop (x, y, w, h), clipping to image bounds."""
    H, W = warped.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return warped[y0:y1, x0:x1]


def _process_page(
    page_idx: int,                 # 1-based
    page_png: Path,
    template: str,
    out_page_dir: Path,
    *,
    save_warped: bool,
) -> dict:
    """Warp + crop one rasterized page; return summary dict."""
    ref_stem = f"{template}-{page_idx}"
    summary: dict = {
        "page": page_idx,
        "ref": ref_stem,
        "status": "ok",
        "cells_written": 0,
    }

    # Schema lookup (page 4+ has no schema).
    try:
        cell_list: list[Cell] = schema_cells(template, page_idx)
    except ValueError as e:
        summary["status"] = f"no_schema: {e}"
        out_page_dir.mkdir(parents=True, exist_ok=True)
        (out_page_dir / "page.json").write_text(json.dumps(summary, indent=2))
        return summary

    # Warp scan -> reference. ``warp_one`` writes warped.png + diag.png +
    # warp.json to a directory we control; we keep them in a scratch
    # subdir and only promote what we want.
    warp_scratch = out_page_dir / "_warp"
    try:
        warp_meta = warp_one(page_png, ref_stem, warp_scratch)
    except Exception as e:                                # noqa: BLE001
        summary["status"] = f"warp_failed: {e}"
        out_page_dir.mkdir(parents=True, exist_ok=True)
        (out_page_dir / "page.json").write_text(json.dumps(summary, indent=2))
        shutil.rmtree(warp_scratch, ignore_errors=True)
        return summary

    warped_path = warp_scratch / f"{page_png.stem}__to__{ref_stem}.png"
    warped = cv2.imread(str(warped_path), cv2.IMREAD_GRAYSCALE)

    cells_dir = out_page_dir / "cells"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_records: list[dict] = []
    for c in cell_list:
        crop = _crop_cell(warped, c.bbox)
        crop_path = cells_dir / f"{c.id}.png"
        cv2.imwrite(str(crop_path), crop)
        cell_records.append({
            "id": c.id,
            "kind": c.kind,
            "bbox": list(c.bbox),
            "file": f"cells/{crop_path.name}",
        })

    summary["cells_written"] = len(cell_records)
    summary["warp"] = {
        "method": warp_meta["method"],
        "matched": warp_meta["matched"],
        "rms_err_px": warp_meta["rms_err_px"],
        "max_err_px": warp_meta["max_err_px"],
    }
    page_json = {
        **summary,
        "cells": cell_records,
    }
    (out_page_dir / "page.json").write_text(json.dumps(page_json, indent=2))

    if save_warped:
        shutil.move(str(warped_path), out_page_dir / "warped.png")
    shutil.rmtree(warp_scratch, ignore_errors=True)
    return summary


def extract_one(
    pdf: Path,
    out_root: Path,
    *,
    dpi: int = 300,
    mesa_id: Optional[str] = None,
    template: Optional[str] = None,
    save_warped: bool = False,
    overwrite: bool = False,
) -> dict:
    """Extract one PDF; return its top-level extraction summary."""
    parsed = _parse_corpus_path(pdf)
    if parsed is None and (mesa_id is None or template is None):
        raise ValueError(
            f"PDF path is not in corpus layout and --mesa-id / --template "
            f"not provided: {pdf}"
        )
    if parsed is not None:
        mesa_id = mesa_id or parsed[0]
        template = template or parsed[1]
    assert mesa_id is not None and template is not None

    out_dir = out_root / mesa_id
    if out_dir.exists():
        if not overwrite:
            existing = out_dir / "extraction.json"
            if existing.exists():
                return {"mesa_id": mesa_id, "status": "skipped (exists)"}
        else:
            shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Rasterize into scratch.
    with tempfile.TemporaryDirectory(prefix="e14-extract-") as td:
        scratch = Path(td)
        try:
            pages = _rasterize(pdf, scratch, dpi)
        except subprocess.CalledProcessError as e:
            top = {
                "mesa_id": mesa_id, "pdf": str(pdf), "template": template,
                "status": f"raster_failed: {e.stderr.decode(errors='replace')[:200]}",
                "pages": [],
            }
            (out_dir / "extraction.json").write_text(json.dumps(top, indent=2))
            return top

        page_summaries = []
        for i, png in enumerate(pages, 1):
            page_summaries.append(_process_page(
                i, png, template, out_dir / f"page-{i}",
                save_warped=save_warped,
            ))

    top = {
        "mesa_id": mesa_id,
        "pdf": str(pdf),
        "template": template,
        "status": "ok",
        "pages": page_summaries,
    }
    (out_dir / "extraction.json").write_text(json.dumps(top, indent=2))
    return top


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-PDF E-14 extraction pipeline")
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True,
                    help="Output root directory (per-mesa subdirs created).")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--mesa-id",
                    help="Override mesa id (12 digits); required for PDFs "
                         "outside the corpus directory layout.")
    ap.add_argument("--template", choices=["regular", "consulado"],
                    help="Override template (else auto from dep code).")
    ap.add_argument("--save-warped", action="store_true",
                    help="Keep the full-page warped PNG per page "
                         "(~10 MB/page; off by default).")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-extract even if <out>/<mesa_id> already exists.")
    args = ap.parse_args()

    if (args.mesa_id or args.template) and len(args.pdfs) > 1:
        ap.error("--mesa-id / --template only valid with a single PDF.")

    for pdf in args.pdfs:
        try:
            summary = extract_one(
                pdf, args.out, dpi=args.dpi,
                mesa_id=args.mesa_id, template=args.template,
                save_warped=args.save_warped, overwrite=args.overwrite,
            )
        except Exception as e:                            # noqa: BLE001
            print(f"  {pdf.name}: ERROR -- {e}")
            continue
        if summary.get("status", "").startswith("skipped"):
            print(f"  {pdf.name}: {summary['status']}")
            continue
        pages = summary.get("pages", [])
        page_status = ", ".join(
            f"p{p['page']}={p.get('cells_written', 0)}c" if p["status"] == "ok"
            else f"p{p['page']}=FAIL"
            for p in pages
        )
        print(f"  {summary['mesa_id']}: {summary['status']}  [{page_status}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
