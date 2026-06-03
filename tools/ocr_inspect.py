#!/usr/bin/env python3
"""Run TrOCR-handwritten on extracted vote-digit strips; emit a self-contained
HTML inspection grid (thumbnail + predicted string per strip).

Pure first-pass visualization -- no labels, no accuracy metric.  The goal
is to eyeball whether off-the-shelf handwritten OCR returns plausible
3-digit numbers for the merged digit strips emitted by extract_e14.py,
or whether we need to train.

Usage:

    uv run --with torch --with transformers --with pillow \\
        python tools/ocr_inspect.py /tmp/e14-sample10 \\
        --model microsoft/trocr-small-handwritten \\
        --out /tmp/e14-ocr.html

Reads every ``*.digits.png`` under the input tree (the merged 3-digit
strips written by extract_e14.py), batches them through TrOCR on CPU,
and writes a single self-contained HTML file with one card per strip:
mesa / page / cell-id label, base64-inlined thumbnail, predicted string.
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
import time
from pathlib import Path

from PIL import Image


def _b64_png(img: Image.Image, max_w: int = 220) -> str:
    """Resize to max_w (keep aspect) and return data: URL."""
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _gather(root: Path) -> list[tuple[str, str, str, Path]]:
    """Return (mesa, page, cell_id, path) for every digit strip under root."""
    items: list[tuple[str, str, str, Path]] = []
    for p in sorted(root.glob("*/page-*/cells/*.digits.png")):
        parts = p.parts
        # .../mesa_id/page-N/cells/<cell_id>.png
        mesa = parts[-4]
        page = parts[-3]
        cell_id = p.stem    # e.g. "r1.cand_1.digits"
        items.append((mesa, page, cell_id, p))
    return items


def _ocr_all(
    items: list[tuple[str, str, str, Path]],
    model_name: str,
    batch_size: int,
) -> list[str]:
    """Run TrOCR on every image, returning the predicted string for each."""
    # Imported lazily so the --help path doesn't pay the torch import cost.
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    print(f"loading {model_name} ...", flush=True)
    t0 = time.perf_counter()
    processor = TrOCRProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name)
    model.eval()
    print(f"  loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    predictions: list[str] = []
    t0 = time.perf_counter()
    with torch.inference_mode():
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            images = [Image.open(p).convert("RGB") for _, _, _, p in batch]
            pixel_values = processor(images=images, return_tensors="pt").pixel_values
            generated_ids = model.generate(pixel_values, max_length=8)
            texts = processor.batch_decode(generated_ids, skip_special_tokens=True)
            predictions.extend(texts)
            print(f"  {i + len(batch):4d}/{len(items)}  "
                  f"({(time.perf_counter() - t0) / (i + len(batch)) * 1000:.0f} ms/strip)",
                  flush=True)
    return predictions


def _render_html(
    items: list[tuple[str, str, str, Path]],
    predictions: list[str],
    model_name: str,
) -> str:
    """Build a self-contained HTML inspection grid."""
    cards: list[str] = []
    for (mesa, page, cell_id, path), pred in zip(items, predictions):
        img = Image.open(path)
        data_url = _b64_png(img)
        cards.append(
            f'<div class="card">'
            f'<div class="lbl">{mesa} / {page} / {cell_id}</div>'
            f'<img src="{data_url}" alt="">'
            f'<div class="pred">{pred or "&lt;empty&gt;"}</div>'
            f'</div>'
        )
    css = """
    body { font-family: ui-monospace, monospace; background: #1a1a1a; color: #eee;
           margin: 16px; }
    h1 { font-size: 14px; font-weight: normal; color: #888; margin: 0 0 12px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
            gap: 12px; }
    .card { background: #2a2a2a; padding: 8px; border-radius: 4px; }
    .lbl { font-size: 10px; color: #888; margin-bottom: 4px; }
    .card img { width: 100%; image-rendering: pixelated; display: block; }
    .pred { font-size: 22px; text-align: center; margin-top: 6px;
            font-weight: bold; color: #fc6; letter-spacing: 4px; }
    """
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>E-14 OCR inspection</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>{len(items)} strips · model: {model_name}</h1>"
        f"<div class='grid'>{''.join(cards)}</div>"
        f"</body></html>"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path,
                    help="extract_e14.py output root (contains <mesa_id>/page-*/cells/)")
    ap.add_argument("--model", default="microsoft/trocr-small-handwritten")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()

    items = _gather(args.root)
    if not items:
        print(f"no *.digits.png found under {args.root}", file=sys.stderr)
        return 1
    print(f"found {len(items)} strips under {args.root}")

    predictions = _ocr_all(items, args.model, args.batch_size)

    html = _render_html(items, predictions, args.model)
    args.out.write_text(html)
    print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
