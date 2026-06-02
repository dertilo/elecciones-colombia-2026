#!/usr/bin/env python3
"""
Stratified-sample eyeball tool for the E-14 corpus.

Picks a handful of PDFs (one per departamento, plus the size extremes),
rasterizes them with `pdftoppm`, runs anchor-based warping against the
matching reference page (regular vs consulado, picked from the dep
code), and writes an HTML contact sheet showing `raw | warped | overlay`
per page plus the transform method + residuals -- visual QA for both
form layout and warp quality across the corpus.

Usage:
    uv run --with pyzbar --with opencv-python-headless --with numpy \\
        python tools/eyeball_e14.py
    xdg-open /tmp/e14-eyeball/index.html
"""

from __future__ import annotations

import argparse
import html
import random
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import cv2

# Re-use the warp helper -- it imports detect_anchors transitively.
_TOOLS = Path(__file__).parent
sys.path.insert(0, str(_TOOLS))
from warp_to_reference import warp_one  # noqa: E402

PATH_RE = re.compile(
    r".*/delegados/(?P<dep>\d{2})/(?P<mun>\d{3})/(?P<zon>\d{3})/(?P<sub>\d{2})/(?P<mesa>\d{3})_[0-9a-f]+\.pdf$"
)


def stratify(root: Path, seed: int) -> list[Path]:
    """One per dep + 5 smallest + 5 largest. Deduped, deterministic."""
    rng = random.Random(seed)
    by_dep: dict[str, list[Path]] = defaultdict(list)
    sized: list[tuple[int, Path]] = []
    for p in root.rglob("*.pdf"):
        m = PATH_RE.match(str(p))
        if not m:
            continue
        by_dep[m["dep"]].append(p)
        sized.append((p.stat().st_size, p))

    picks: set[Path] = set()
    for dep, paths in sorted(by_dep.items()):
        picks.add(rng.choice(paths))
    sized.sort()
    for _, p in sized[:5]:
        picks.add(p)
    for _, p in sized[-5:]:
        picks.add(p)
    return sorted(picks)


def rasterize(pdf: Path, out_dir: Path, dpi: int) -> list[Path]:
    """pdftoppm → list of generated PNG paths."""
    stem = pdf.stem.split("_", 1)[0] + "_" + pdf.parent.parts[-1]  # mesa+sub for uniqueness
    # Use a hash of the full path to avoid collisions across deps
    tag = f"{pdf.parts[-5]}{pdf.parts[-4]}{pdf.parts[-3]}{pdf.parts[-2]}_{pdf.stem.split('_', 1)[0]}"
    prefix = out_dir / tag
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)],
        check=True,
        capture_output=True,
    )
    return sorted(out_dir.glob(f"{tag}-*.png"))


def _template_for_dep(dep: str) -> str:
    """Pick the template family for a dep code (88 -> consulado, else regular)."""
    return "consulado" if dep == "88" else "regular"


def _thumb(src: Path, dst: Path, height: int = 380) -> None:
    img = cv2.imread(str(src))
    if img is None:
        return
    h, w = img.shape[:2]
    scale = height / h
    cv2.imwrite(str(dst), cv2.resize(img, (int(w * scale), height)))


def warp_pages(pdf: Path, pngs: list[Path], out_dir: Path) -> list[dict]:
    """Warp each rasterized page to its reference; return per-page metadata.

    Each dict contains: ``page`` (1-based), ``raw_thumb``, ``warp_thumb``,
    ``diag_thumb`` (filenames in ``out_dir``, relative), and a status line.
    Missing pieces are recorded as ``None`` so the renderer can show a
    "warp failed" placeholder instead of crashing.
    """
    m = PATH_RE.match(str(pdf))
    dep = m["dep"] if m else "??"
    template = _template_for_dep(dep)

    results: list[dict] = []
    warp_subdir = out_dir / "warp"
    warp_subdir.mkdir(exist_ok=True)
    for idx, png in enumerate(pngs, 1):
        # Reference page index: 1/2/3 maps directly; anything else uses
        # page 1 as a best-effort fallback so the visual still appears.
        ref_page = idx if idx <= 3 else 1
        ref_stem = f"{template}-{ref_page}"

        raw_thumb = out_dir / f"{png.stem}_raw_thumb.png"
        _thumb(png, raw_thumb)

        entry: dict = {
            "page": idx,
            "ref": ref_stem,
            "raw_thumb": raw_thumb.name,
            "warp_thumb": None,
            "diag_thumb": None,
            "status": "",
        }
        try:
            meta = warp_one(png, ref_stem, warp_subdir)
        except Exception as e:
            entry["status"] = f"warp failed: {e}"
            results.append(entry)
            continue

        warp_path = warp_subdir / f"{png.stem}__to__{ref_stem}.png"
        diag_path = warp_subdir / f"{png.stem}__to__{ref_stem}_diag.png"
        warp_thumb = out_dir / f"{png.stem}_warp_thumb.png"
        diag_thumb = out_dir / f"{png.stem}_diag_thumb.png"
        _thumb(warp_path, warp_thumb)
        _thumb(diag_path, diag_thumb)
        entry["warp_thumb"] = warp_thumb.name
        entry["diag_thumb"] = diag_thumb.name
        entry["status"] = (
            f"{meta['method']} via {','.join(meta['matched'])}  "
            f"RMS={meta['rms_err_px']:.1f}px  max={meta['max_err_px']:.1f}px"
        )
        results.append(entry)
    return results


def render_html(
    items: list[tuple[Path, list[Path], list[dict]]],
    out_dir: Path,
) -> Path:
    rows: list[str] = []
    for pdf, _pngs, page_metas in items:
        m = PATH_RE.match(str(pdf))
        meta = (
            f"dep={m['dep']} mun={m['mun']} zon={m['zon']} sub={m['sub']} mesa={m['mesa']}"
            if m
            else pdf.name
        )
        size_kb = pdf.stat().st_size / 1024
        template = _template_for_dep(m["dep"]) if m else "?"

        page_cells: list[str] = []
        for pm in page_metas:
            triple = []
            for label, key in (("raw", "raw_thumb"), ("warped", "warp_thumb"), ("overlay", "diag_thumb")):
                name = pm.get(key)
                if name:
                    triple.append(
                        f'<div class="thumb"><div class="lbl">{label}</div>'
                        f'<a href="{html.escape(name)}" target="_blank">'
                        f'<img src="{html.escape(name)}" loading="lazy"></a></div>'
                    )
                else:
                    triple.append(
                        f'<div class="thumb missing"><div class="lbl">{label}</div>'
                        f'<div class="placeholder">—</div></div>'
                    )
            status_cls = "ok"
            if "failed" in pm["status"] or not pm.get("warp_thumb"):
                status_cls = "bad"
            page_cells.append(
                f'<div class="page">'
                f'<div class="phead">p{pm["page"]} → {html.escape(pm["ref"])}</div>'
                f'<div class="triple">{"".join(triple)}</div>'
                f'<div class="status {status_cls}">{html.escape(pm["status"])}</div>'
                f'</div>'
            )
        rows.append(
            f'<tr><td class="meta"><div class="path">{html.escape(str(pdf))}</div>'
            f'<div>{html.escape(meta)}</div>'
            f'<div>template={html.escape(template)} · {size_kb:,.0f} KB · {len(page_metas)} pages</div></td>'
            f'<td class="pages">{"".join(page_cells)}</td></tr>'
        )
    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>E-14 eyeball + warp</title>
<style>
body {{ font: 12px/1.4 system-ui, sans-serif; margin: 1em; }}
table {{ border-collapse: collapse; width: 100%; }}
td {{ border-top: 1px solid #ddd; padding: .5em; vertical-align: top; }}
.meta {{ width: 22em; word-break: break-all; }}
.meta .path {{ color: #666; font-size: 10px; }}
.pages {{ display: flex; flex-wrap: wrap; gap: 1em; }}
.page {{ border: 1px solid #ccc; padding: .4em; background: #fafafa; }}
.phead {{ font-weight: bold; margin-bottom: .3em; }}
.triple {{ display: flex; gap: .4em; }}
.thumb {{ text-align: center; }}
.thumb .lbl {{ font-size: 10px; color: #666; }}
.thumb img {{ height: 360px; border: 1px solid #ccc; }}
.thumb.missing .placeholder {{
    height: 360px; width: 120px; line-height: 360px; color: #aaa;
    border: 1px dashed #ccc;
}}
.status {{ margin-top: .3em; font-family: ui-monospace, monospace; font-size: 11px; }}
.status.ok {{ color: #060; }}
.status.bad {{ color: #c00; }}
</style></head>
<body>
<h1>E-14 stratified sample + warp QA ({len(items)} PDFs)</h1>
<p>Per page: raw scan · warped to reference · ref⊕warped overlay
(red = ref only, green = warped only, yellow = aligned).
Status line: transform method, matched anchors, RMS/max reprojection error.</p>
<table>{"".join(rows)}</table>
</body></html>
"""
    idx = out_dir / "index.html"
    idx.write_text(html_doc)
    return idx


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", default="data_2026/e14/delegados")
    p.add_argument("--out", default="/tmp/e14-eyeball")
    p.add_argument("--dpi", type=int, default=300,
                   help="rasterization DPI; 300 matches reference frames and "
                        "is needed for reliable anchor detection")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--clean", action="store_true", help="wipe --out first")
    args = p.parse_args()

    root = Path(args.corpus).resolve()
    if not root.is_dir():
        print(f"Corpus not found: {root}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    picks = stratify(root, args.seed)
    print(f"[stratify] {len(picks)} PDFs selected")

    items: list[tuple[Path, list[Path], list[dict]]] = []
    for i, pdf in enumerate(picks, 1):
        try:
            pngs = rasterize(pdf, out_dir, args.dpi)
        except subprocess.CalledProcessError as e:
            print(f"  [{i:>3}/{len(picks)}] FAIL rasterize {pdf}: {e.stderr.decode()[:200]}",
                  file=sys.stderr)
            continue
        try:
            page_metas = warp_pages(pdf, pngs, out_dir)
        except Exception as e:
            print(f"  [{i:>3}/{len(picks)}] FAIL warp {pdf}: {e}", file=sys.stderr)
            page_metas = []
        method_summary = ",".join(pm.get("status", "?").split()[0] for pm in page_metas) or "—"
        print(f"  [{i:>3}/{len(picks)}] {pdf.parts[-5]}/.../{pdf.name[:24]}…  "
              f"-> {len(pngs)} pages  [{method_summary}]")
        items.append((pdf, pngs, page_metas))

    idx = render_html(items, out_dir)
    print(f"\n[done] {idx}")
    print(f"[open] xdg-open {idx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
