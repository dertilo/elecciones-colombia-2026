#!/usr/bin/env python3
"""
Stratified-sample eyeball tool for the E-14 corpus.

Picks a handful of PDFs (one per departamento, plus the size extremes),
rasterizes them with `pdftoppm`, and writes an HTML contact sheet so the
forms can be inspected at a glance before committing to a template /
segmentation strategy.

Usage:
    uv run python tools/eyeball_e14.py
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


def render_html(items: list[tuple[Path, list[Path]]], out_dir: Path) -> Path:
    rows: list[str] = []
    for pdf, pngs in items:
        m = PATH_RE.match(str(pdf))
        meta = (
            f"dep={m['dep']} mun={m['mun']} zon={m['zon']} sub={m['sub']} mesa={m['mesa']}"
            if m
            else pdf.name
        )
        size_kb = pdf.stat().st_size / 1024
        thumbs = "".join(
            f'<a href="{html.escape(p.name)}" target="_blank">'
            f'<img src="{html.escape(p.name)}" loading="lazy"></a>'
            for p in pngs
        )
        rows.append(
            f'<tr><td class="meta"><div class="path">{html.escape(str(pdf))}</div>'
            f'<div>{html.escape(meta)}</div>'
            f'<div>{size_kb:,.0f} KB · {len(pngs)} pages</div></td>'
            f'<td class="thumbs">{thumbs}</td></tr>'
        )
    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>E-14 eyeball</title>
<style>
body {{ font: 12px/1.4 system-ui, sans-serif; margin: 1em; }}
table {{ border-collapse: collapse; width: 100%; }}
td {{ border-top: 1px solid #ddd; padding: .5em; vertical-align: top; }}
.meta {{ width: 22em; word-break: break-all; }}
.meta .path {{ color: #666; font-size: 10px; }}
.thumbs img {{ height: 380px; margin-right: .5em; border: 1px solid #ccc; }}
</style></head>
<body>
<h1>E-14 stratified sample ({len(items)} PDFs)</h1>
<p>Click any thumbnail for the full-resolution PNG.</p>
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
    p.add_argument("--dpi", type=int, default=120, help="rasterization DPI; 120 is enough for eyeballing layout")
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

    items: list[tuple[Path, list[Path]]] = []
    for i, pdf in enumerate(picks, 1):
        try:
            pngs = rasterize(pdf, out_dir, args.dpi)
            print(f"  [{i:>3}/{len(picks)}] {pdf.parts[-5]}/.../{pdf.name[:24]}…  -> {len(pngs)} pages")
            items.append((pdf, pngs))
        except subprocess.CalledProcessError as e:
            print(f"  [{i:>3}/{len(picks)}] FAIL {pdf}: {e.stderr.decode()[:200]}", file=sys.stderr)

    idx = render_html(items, out_dir)
    print(f"\n[done] {idx}")
    print(f"[open] xdg-open {idx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
