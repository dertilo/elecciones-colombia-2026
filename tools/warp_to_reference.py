"""Warp a scanned E-14 page to its reference frame using anchor matching.

Workflow per scan:
  1. Detect anchors on the scan with ``detect_anchors.detect_anchors``.
  2. Load cached anchors for the chosen reference (``--ref regular-1`` etc.)
     from ``data_2026/templates/anchors/<ref>.json``.
  3. Match anchors by name.  Available matches drive the transform choice:

       4-pt perspective   -- preferred; needs >=4 named pairs.  We weight
                             towards the four corner squares because they
                             are the most-spread, lowest-error reference
                             points; ``barcode`` / ``header_bar`` are used
                             as fillers when corners are missing (e.g. top
                             of phone-photo scans cropped out of frame).
       3-pt affine        -- exactly 3 named pairs; preserves parallel lines.
       2-pt similarity    -- 2 named pairs; translate + rotate + uniform scale.
       fail               -- < 2 matches; warp is undefined.

  4. Warp the scan to the reference page size, write
       data_2026/templates/warped/<scan-stem>__to__<ref-stem>.png
     and a thumb-sized side-by-side diagnostic
       data_2026/templates/warped/<scan-stem>__to__<ref-stem>_diag.png

A small JSON sibling records the transform method, the matched anchor
names, and the per-point reprojection error (max + RMS) so we can audit
warp quality across the corpus without re-opening every image.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "tools"))

from detect_anchors import Anchor, detect_anchors  # noqa: E402

_ANCHOR_DIR = _REPO / "data_2026" / "templates" / "anchors"
_REF_DIR = _REPO / "data_2026" / "templates" / "ref"
_OUT_DIR = _REPO / "data_2026" / "templates" / "warped"

# Corner-square anchors first -- they are the most reliable and the most
# spread out, so any 4-pt fit should prefer them.  ``barcode`` and
# ``header_bar`` come last and only fill gaps.
_PREFERRED_ORDER = (
    "corner_tl", "corner_tr", "corner_bl", "corner_br",
    "barcode", "header_bar",
)


@dataclass
class WarpResult:
    method: str                 # "perspective" | "affine" | "similarity"
    matched: list[str]          # anchor names used
    M: np.ndarray               # 3x3 (perspective) or 2x3 (affine/similarity)
    # Residual semantics depend on mode:
    #   perspective: only the first 4 matches define M, so their residual
    #     is mechanically 0; reported RMS/max is the *cross-check* of the
    #     remaining auxiliary anchors (barcode, header_bar) against the
    #     corner-based homography.  Large values here usually mean the
    #     reference and the scan disagree on aux-anchor positions
    #     (template-version drift), NOT that the corner warp itself is
    #     bad -- inspect the diag overlay to be sure.
    #   affine (3 pts) / similarity (2 pts): residual is mechanically 0
    #     because the fit consumes exactly the DoF of the transform; the
    #     metric is uninformative.
    rms_err: float
    max_err: float


def _anchors_by_name(anchors: list[Anchor]) -> dict[str, Anchor]:
    return {a.name: a for a in anchors}


def _load_ref_anchors(ref_stem: str) -> tuple[dict[str, Anchor], tuple[int, int]]:
    payload = json.loads((_ANCHOR_DIR / f"{ref_stem}.json").read_text())
    anchors = [Anchor(**{k: v for k, v in a.items() if k in {"name", "polygon", "center", "payload"}})
               for a in payload["anchors"]]
    H, W = payload["shape"]
    return _anchors_by_name(anchors), (H, W)


def _select_pairs(
    scan: dict[str, Anchor],
    ref: dict[str, Anchor],
) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    """Return matched (name, scan_center, ref_center) tuples, preferred order."""
    pairs = []
    for name in _PREFERRED_ORDER:
        if name in scan and name in ref:
            pairs.append((
                name,
                (float(scan[name].center[0]), float(scan[name].center[1])),
                (float(ref[name].center[0]), float(ref[name].center[1])),
            ))
    return pairs


def _fit_transform(
    pairs: list[tuple[str, tuple[float, float], tuple[float, float]]],
) -> WarpResult:
    if len(pairs) < 2:
        raise RuntimeError(f"need at least 2 matched anchors, got {len(pairs)}: "
                           f"{[p[0] for p in pairs]}")

    src = np.array([p[1] for p in pairs], dtype=np.float32)
    dst = np.array([p[2] for p in pairs], dtype=np.float32)
    names = [p[0] for p in pairs]

    if len(pairs) >= 4:
        # Use the first 4 in preferred order for an exact perspective fit.
        # (Could use cv2.findHomography on all matches with RANSAC, but with
        # very few, well-trusted points the exact 4-pt transform is better.)
        M = cv2.getPerspectiveTransform(src[:4], dst[:4])
        method = "perspective"
        # Project all matched points to measure residuals -- pts 4+ are out-of-sample.
        src_h = np.concatenate([src, np.ones((len(src), 1), dtype=np.float32)], axis=1)
        proj = (M @ src_h.T).T
        proj = proj[:, :2] / proj[:, 2:3]
    elif len(pairs) == 3:
        M = cv2.getAffineTransform(src, dst)
        method = "affine"
        proj = (M @ np.concatenate([src, np.ones((3, 1), dtype=np.float32)], axis=1).T).T
    else:
        # 2 points -> similarity (translate + rotate + uniform scale).
        # estimateAffinePartial2D requires at least 2 pairs; with exactly 2
        # it returns the unique similarity that maps them.
        M, _ = cv2.estimateAffinePartial2D(
            src.reshape(-1, 1, 2), dst.reshape(-1, 1, 2), method=cv2.LMEDS,
        )
        if M is None:
            raise RuntimeError(f"similarity fit failed on {names}")
        method = "similarity"
        proj = (M @ np.concatenate([src, np.ones((2, 1), dtype=np.float32)], axis=1).T).T

    errs = np.linalg.norm(proj - dst, axis=1)
    return WarpResult(
        method=method,
        matched=names,
        M=M,
        rms_err=float(np.sqrt(np.mean(errs ** 2))),
        max_err=float(np.max(errs)),
    )


def _warp(img: np.ndarray, res: WarpResult, ref_hw: tuple[int, int]) -> np.ndarray:
    H, W = ref_hw
    if res.method == "perspective":
        return cv2.warpPerspective(img, res.M, (W, H), flags=cv2.INTER_LINEAR,
                                   borderValue=255)
    return cv2.warpAffine(img, res.M, (W, H), flags=cv2.INTER_LINEAR,
                          borderValue=255)


def _diagnostic(warped_gray: np.ndarray, ref_path: Path) -> np.ndarray:
    """Build a small side-by-side: ref | warped | overlay (red=ref, green=warped)."""
    ref = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
    # Resize all to a manageable thumb width.
    target_w = 800
    H, W = ref.shape
    scale = target_w / W
    new_size = (target_w, int(H * scale))
    ref_t = cv2.resize(ref, new_size)
    warp_t = cv2.resize(warped_gray, new_size)
    # Color overlay: ref in red, warped in green -> aligned = yellow.
    overlay = np.zeros((new_size[1], new_size[0], 3), dtype=np.uint8)
    overlay[..., 2] = 255 - ref_t       # red shows ref ink
    overlay[..., 1] = 255 - warp_t      # green shows warped ink
    ref_bgr = cv2.cvtColor(ref_t, cv2.COLOR_GRAY2BGR)
    warp_bgr = cv2.cvtColor(warp_t, cv2.COLOR_GRAY2BGR)
    sep = np.full((new_size[1], 10, 3), 0, dtype=np.uint8)
    return np.concatenate([ref_bgr, sep, warp_bgr, sep, overlay], axis=1)


def warp_one(scan_path: Path, ref_stem: str, out_dir: Path) -> dict:
    ref_anchors, ref_hw = _load_ref_anchors(ref_stem)
    scan_anchors_list, _ = detect_anchors(scan_path)
    scan_anchors = _anchors_by_name(scan_anchors_list)

    pairs = _select_pairs(scan_anchors, ref_anchors)
    res = _fit_transform(pairs)

    scan_img = cv2.imread(str(scan_path), cv2.IMREAD_GRAYSCALE)
    warped = _warp(scan_img, res, ref_hw)

    stem = f"{scan_path.stem}__to__{ref_stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    warped_path = out_dir / f"{stem}.png"
    cv2.imwrite(str(warped_path), warped)
    diag = _diagnostic(warped, _REF_DIR / f"{ref_stem}.png")
    cv2.imwrite(str(out_dir / f"{stem}_diag.png"), diag)

    meta = {
        "scan": str(scan_path),
        "ref": ref_stem,
        "ref_shape": list(ref_hw),
        "method": res.method,
        "matched": res.matched,
        "rms_err_px": res.rms_err,
        "max_err_px": res.max_err,
        "scan_anchors": [a.name for a in scan_anchors_list],
        "M": res.M.tolist(),
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Warp a scan to its reference frame")
    ap.add_argument("scans", nargs="+", type=Path,
                    help="One or more rasterized scan PNGs (one page per file).")
    ap.add_argument("--ref", required=True,
                    help="Reference stem, e.g. regular-1 or consulado-1.")
    ap.add_argument("--out", type=Path, default=_OUT_DIR,
                    help=f"Output directory (default: {_OUT_DIR.relative_to(_REPO)}).")
    args = ap.parse_args()

    print(f"Reference: {args.ref}")
    for scan in args.scans:
        try:
            meta = warp_one(scan, args.ref, args.out)
        except Exception as e:
            print(f"  {scan.name}: FAILED -- {e}")
            continue
        print(f"  {scan.name}: {meta['method']:11s} via {meta['matched']}  "
              f"RMS={meta['rms_err_px']:.1f}px  max={meta['max_err_px']:.1f}px")


if __name__ == "__main__":
    main()
