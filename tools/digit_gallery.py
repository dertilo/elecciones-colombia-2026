#!/usr/bin/env python3
"""Build an HTML gallery of all extracted 3-digit strips.

Each card shows a thumbnail with mesa / page / cell-id label.  Clicking
the thumbnail opens the source PDF in a new browser tab (file:// URL
resolved against ``--repo-root``).

Two output modes:

* **Single page** -- ``--out gallery.html``.  All strips inlined as
  base64 data URLs.  Self-contained, portable, but quickly impractical
  beyond a few thousand strips.

* **Chunked / disk-backed** -- ``--out gallery_dir/``.  Strips referenced
  with relative paths to the on-disk PNGs (no base64).  Emits one
  ``z<zona>.html`` per electoral zona plus an ``index.html`` linking
  them.  Scales to hundreds of thousands of strips.

Multiple extraction trees can be combined with ``--source NAME=PATH``,
e.g. ``--source delegados=...`` and ``--source transmision=...``; each
card is labelled with its source.

Usage::

    # Small sample, single page
    uv run --with pillow python tools/digit_gallery.py \\
        --source data=/tmp/e14-sample10 \\
        --out /tmp/e14-gallery.html

    # Full Medellin, chunked
    uv run --with pillow python tools/digit_gallery.py \\
        --source delegados=data_2026/e14_extract/01/001/delegados \\
        --source transmision=data_2026/e14_extract/01/001/transmision \\
        --out data_2026/e14_extract/01/001/gallery

The extraction tree(s) are expected to follow ``extract_e14.py``'s
layout: ``<source>/<mesa_id>/extraction.json`` (PDF path) and
``<source>/<mesa_id>/page-*/cells/*.digits.png`` (strips).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class Strip:
    source: str       # e.g. "delegados"
    mesa: str         # e.g. "0100100602018"
    page: str         # e.g. "page-1"
    cell_id: str      # e.g. "r1.cand_1.digits"
    path: Path        # absolute path to PNG
    pdf_url: str      # absolute file:// URL of source PDF (may be "")

    @property
    def zona(self) -> str:
        # mesa = DD MMM ZZZ PP MMM  (2 + 3 + 3 + 2 + 3 = 13 chars)
        return self.mesa[5:8] if len(self.mesa) >= 8 else "???"


def _b64_png(img: Image.Image, max_w: int = 220) -> str:
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _gather(source: str, root: Path, repo_root: Path) -> list[Strip]:
    """Walk one extraction tree; return one Strip per ``*.digits.png``."""
    pdf_url_cache: dict[str, str] = {}
    strips: list[Strip] = []
    for p in sorted(root.glob("*/page-*/cells/*.digits.png")):
        parts = p.parts
        mesa = parts[-4]
        page = parts[-3]
        cell_id = p.stem

        if mesa not in pdf_url_cache:
            extraction = root / mesa / "extraction.json"
            try:
                meta = json.loads(extraction.read_text())
                rel = meta.get("pdf", "")
                pdf_url_cache[mesa] = (repo_root / rel).resolve().as_uri() if rel else ""
            except (OSError, json.JSONDecodeError):
                pdf_url_cache[mesa] = ""

        strips.append(Strip(source, mesa, page, cell_id, p, pdf_url_cache[mesa]))
    return strips


CSS = """
body { font-family: ui-monospace, monospace; background: #1a1a1a; color: #eee;
       margin: 16px; }
h1 { font-size: 14px; font-weight: normal; color: #888; margin: 0 0 12px; }
nav { font-size: 12px; color: #888; margin-bottom: 16px; line-height: 1.8; }
nav a { color: #fc6; text-decoration: none; margin-right: 10px; }
nav a:hover { text-decoration: underline; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        gap: 12px; }
.card { background: #2a2a2a; padding: 8px; border-radius: 4px; }
.lbl { font-size: 10px; color: #888; margin-bottom: 4px;
       overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src { color: #6cf; }
.card img { width: 100%; image-rendering: pixelated; display: block; }
.card a { display: block; cursor: zoom-in; }
.card a:hover img { outline: 2px solid #fc6; }
"""


def _card_html(s: Strip, img_src: str) -> str:
    thumb = f'<img src="{img_src}" alt="" loading="lazy">'
    if s.pdf_url:
        thumb = (f'<a href="{s.pdf_url}" target="_blank" rel="noopener" '
                 f'title="open {s.mesa} PDF">{thumb}</a>')
    return (
        f'<div class="card">'
        f'<div class="lbl"><span class="src">{s.source}</span> '
        f'{s.mesa} / {s.page} / {s.cell_id}</div>'
        f'{thumb}'
        f'</div>'
    )


def _render_page(title: str, header: str, cards: list[str], nav: str = "") -> str:
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{CSS}</style></head><body>"
        f"<h1>{header}</h1>"
        f"{nav}"
        f"<div class='grid'>{''.join(cards)}</div>"
        f"</body></html>"
    )


def _write_single(strips: list[Strip], out: Path) -> None:
    """Single-page mode: inline base64 thumbnails."""
    cards = [_card_html(s, _b64_png(Image.open(s.path))) for s in strips]
    header = (f"{len(strips)} strips &middot; "
              f"click thumbnail to open source PDF")
    out.write_text(_render_page("E-14 digit-strip gallery", header, cards))


def _write_chunked(strips: list[Strip], out_dir: Path) -> None:
    """Chunked mode: one HTML per zona + index, relative img paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_zona: dict[str, list[Strip]] = defaultdict(list)
    for s in strips:
        by_zona[s.zona].append(s)

    zonas = sorted(by_zona.keys())
    nav_links = " ".join(
        f'<a href="z{z}.html">z{z} ({len(by_zona[z])})</a>' for z in zonas
    )
    nav = f'<nav><a href="index.html">index</a> {nav_links}</nav>'

    for zona in zonas:
        zstrips = by_zona[zona]
        cards = []
        for s in zstrips:
            rel = os.path.relpath(s.path, out_dir)
            cards.append(_card_html(s, rel))
        header = (f"zona <b>{zona}</b> &middot; {len(zstrips)} strips "
                  f"&middot; click thumbnail to open source PDF")
        page = _render_page(
            f"E-14 gallery zona {zona}", header, cards, nav=nav,
        )
        (out_dir / f"z{zona}.html").write_text(page)

    # index.html: nav + per-zona summary table
    td = 'style="padding:4px 12px;"'
    rows_html = []
    for zona in zonas:
        zstrips = by_zona[zona]
        mesas = {s.mesa for s in zstrips}
        sources = sorted({s.source for s in zstrips})
        rows_html.append(
            f'<tr>'
            f'<td {td}><a href="z{zona}.html">z{zona}</a></td>'
            f'<td {td} align="right">{len(zstrips):,}</td>'
            f'<td {td} align="right">{len(mesas):,}</td>'
            f'<td {td}>{", ".join(sources)}</td>'
            f'</tr>'
        )
    table = (
        '<table style="border-collapse: collapse; font-size: 13px;">'
        '<tr style="color:#888;border-bottom:1px solid #444;">'
        f'<th {td} align="left">zona</th>'
        f'<th {td} align="right">strips</th>'
        f'<th {td} align="right">mesas</th>'
        f'<th {td} align="left">sources</th>'
        '</tr>'
        + "".join(rows_html)
        + '</table>'
    )
    total_mesas = len({s.mesa for s in strips})
    header = (
        f"E-14 digit-strip gallery &middot; {len(strips):,} strips "
        f"&middot; {total_mesas:,} mesas &middot; {len(zonas)} zonas"
    )
    body = (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>E-14 gallery index</title><style>{CSS}</style></head><body>"
        f"<h1>{header}</h1>{nav}{table}</body></html>"
    )
    (out_dir / "index.html").write_text(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source", action="append", required=True, metavar="NAME=PATH",
        help="extraction tree; repeatable.  Path must contain "
             "<mesa>/page-*/cells/*.digits.png",
    )
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    ap.add_argument(
        "--out", type=Path, required=True,
        help="single .html file (inline base64) OR directory (chunked + "
             "relative img paths)",
    )
    args = ap.parse_args()

    sources: list[tuple[str, Path]] = []
    for spec in args.source:
        if "=" not in spec:
            print(f"--source must be NAME=PATH (got {spec!r})", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        sources.append((name, Path(path)))

    all_strips: list[Strip] = []
    repo_root = args.repo_root.resolve()
    for name, root in sources:
        s = _gather(name, root, repo_root)
        print(f"  {name}: {len(s):,} strips under {root}")
        all_strips.extend(s)
    if not all_strips:
        print("no *.digits.png found in any source", file=sys.stderr)
        return 1
    print(f"total: {len(all_strips):,} strips")

    if args.out.suffix == ".html":
        _write_single(all_strips, args.out)
        print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")
    else:
        _write_chunked(all_strips, args.out)
        n = len(list(args.out.glob("*.html")))
        print(f"wrote {n} HTML files under {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
