#!/usr/bin/env python3
"""Embed extracted digit crops via MobileNet-v3 and visualize with UMAP.

Reads digit PNGs from a per-mesa extraction tree (output of
``extract_e14.py``), embeds each via MobileNet-v3-small
(ImageNet-pretrained, classifier head stripped) into a 576-dim feature
vector, reduces to 2D via UMAP, and writes a self-contained HTML scatter
where every point is the digit thumbnail at its UMAP position.

Crops are letterboxed (not stretched) to 224x224 so digit aspect ratio
is preserved -- our crops are ~1:2 and stretching them would inject
spurious shape information into the embedding.

Usage:
    uv run --with torch --with torchvision --with umap-learn \\
        --with opencv-python-headless --with numpy \\
        python tools/embed_umap.py /tmp/e14-sample10 --out /tmp/e14-umap.html
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision.models as M
import umap

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _load_model() -> torch.nn.Module:
    weights = M.MobileNet_V3_Small_Weights.IMAGENET1K_V1
    model = M.mobilenet_v3_small(weights=weights)
    model.classifier = torch.nn.Identity()
    model.eval()
    return model


def _letterbox(img: np.ndarray, target: int = 224, pad: int = 255) -> np.ndarray:
    """Resize longest side to ``target``, pad shorter side with ``pad`` (white)."""
    h, w = img.shape[:2]
    scale = target / max(h, w)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    pad_w = target - new_w
    pad_h = target - new_h
    top = pad_h // 2
    bottom = pad_h - top
    left = pad_w // 2
    right = pad_w - left
    return cv2.copyMakeBorder(
        resized, top, bottom, left, right,
        cv2.BORDER_CONSTANT, value=[pad, pad, pad],
    )


def _to_tensor(img_bgr: np.ndarray) -> torch.Tensor:
    """BGR uint8 HWC -> normalized RGB float32 CHW tensor."""
    boxed = _letterbox(img_bgr, 224)
    rgb = cv2.cvtColor(boxed, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - _IMAGENET_MEAN) / _IMAGENET_STD
    return torch.from_numpy(rgb).permute(2, 0, 1)


def embed(paths: list[Path], batch_size: int = 32) -> np.ndarray:
    model = _load_model()
    out_chunks: list[np.ndarray] = []
    for i in range(0, len(paths), batch_size):
        batch_paths = paths[i:i + batch_size]
        tensors = []
        for p in batch_paths:
            im = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if im is None:
                raise RuntimeError(f"failed to read {p}")
            tensors.append(_to_tensor(im))
        batch = torch.stack(tensors)
        with torch.no_grad():
            feats = model(batch).cpu().numpy()
        out_chunks.append(feats)
        if i % (batch_size * 4) == 0:
            print(f"  embedded {i + len(batch_paths)}/{len(paths)}",
                  file=sys.stderr)
    return np.concatenate(out_chunks)


def _thumb_b64(path: Path, max_dim: int = 64) -> str:
    im = cv2.imread(str(path))
    h, w = im.shape[:2]
    scale = max_dim / max(h, w)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    im = cv2.resize(im, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        raise RuntimeError(f"png encode failed for {path}")
    return base64.b64encode(buf.tobytes()).decode()


def write_html(paths: list[Path], xy: np.ndarray, out: Path,
               canvas: int = 2200, thumb: int = 56) -> None:
    """Self-contained HTML: thumbnails positioned at normalized UMAP coords."""
    x = xy[:, 0]
    y = xy[:, 1]
    x_n = (x - x.min()) / (np.ptp(x) or 1.0)
    y_n = (y - y.min()) / (np.ptp(y) or 1.0)

    items: list[str] = []
    for p, xn, yn in zip(paths, x_n, y_n):
        b64 = _thumb_b64(p, max_dim=thumb)
        title = "/".join(p.parts[-4:])
        px = int(xn * (canvas - thumb))
        py = int(yn * (canvas - thumb))
        items.append(
            f'<img src="data:image/png;base64,{b64}" '
            f'style="left:{px}px;top:{py}px;max-height:{thumb}px;" '
            f'title="{title}">'
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>E-14 digit UMAP ({len(paths)} crops)</title>
<style>
body {{ margin:0; background:#222; font-family:sans-serif; color:#ccc; }}
.toolbar {{ padding:8px 12px; }}
.canvas {{ position:relative; width:{canvas}px; height:{canvas}px;
            background:#fafafa; margin:0 12px 12px; border:1px solid #444; }}
img {{ position:absolute; background:white; image-rendering:crisp-edges;
       box-shadow:0 0 0 1px #ccc; }}
img:hover {{ z-index:1000; box-shadow:0 0 0 2px red;
             transform:scale(2.5); transform-origin:center; }}
</style></head>
<body>
<div class="toolbar">{len(paths)} digit crops | MobileNet-v3-small features (576-dim) | UMAP 2D | hover to zoom</div>
<div class="canvas">
{"".join(items)}
</div></body></html>
"""
    out.write_text(html)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", type=Path,
                    help="Extraction root (e.g. /tmp/e14-sample10)")
    ap.add_argument("--out", type=Path, default=Path("/tmp/e14-umap.html"))
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--min-dist", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()

    paths = sorted(args.root.glob("*/page-*/cells/*.png"))
    print(f"found {len(paths)} crops in {args.root}", file=sys.stderr)
    if not paths:
        print("no crops found", file=sys.stderr)
        return 1

    print("loading MobileNet-v3-small (ImageNet)...", file=sys.stderr)
    print("embedding...", file=sys.stderr)
    embs = embed(paths, batch_size=args.batch_size)
    print(f"  embs shape: {embs.shape}", file=sys.stderr)

    print("UMAP -> 2D...", file=sys.stderr)
    reducer = umap.UMAP(
        n_components=2, n_neighbors=args.n_neighbors,
        min_dist=args.min_dist, random_state=args.seed,
    )
    xy = reducer.fit_transform(embs)

    print(f"writing {args.out}...", file=sys.stderr)
    write_html(paths, xy, args.out)
    print(f"done -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
