# Findings from the 2026-06-02 full scrape

Day-after recap from the first complete pull of the 2026 presidential E-14s.

- **121 844 / 121 844 PDFs**, 22 GB on disk under `data_2026/e14/delegados/`.
  Manifest: `data_2026/e14/delegados/_manifest.jsonl`. (The corpus is
  **delegados**, not transmisión — the original portal label in the
  scraper was swapped; fixed.)
- ~4h 17min total at `--concurrency 6 --delay-ms 200` → **7.9 req/s sustained**,
  **not a single 429 or 403**. Akamai accepts that rate without trouble as
  long as `curl_cffi` runs with `impersonate="chrome"`.
- Mean PDF size ~190 KB — the early 100 KB guess was too low. The
  Consulado scans shift the tail, so total is 22 GB instead of the
  projected 12.
- 12 timeouts during the run, **all in `dep=27` (Chocó)**, all succeeded
  on immediate retry. Looks like a CDN / origin-shard hiccup rather than
  rate limiting — treat it as an indicator, don't overreact.

## Side notes worth keeping

- `dep=88` = Consulados (polling stations at consulates abroad). Those PDFs
  are 50–100× larger than the average (~9 MB vs ~100 KB), likely scanned
  at higher resolution. Budget for that when sizing bandwidth/storage.
- **The dep=88 size inflation is not uniform scanning** — a substantial
  chunk are smartphone photos of the printed form rather than flatbed
  scans. Distribution within dep=88 (3 591 PDFs total):
  - ~1 080 PDFs <200 KB — properly scanned, behave like the rest of the
    corpus.
  - ~1 060 PDFs 200 KB–2 MB — compressed phone photos.
  - ~1 450 PDFs >2 MB (some 30+ MB) — raw phone photos, form floats on a
    larger canvas (visible desk, dark borders, occasional oblique-light
    reflections).
  Concentrated in several consulates — `mun=815` alone contributes 348 —
  not USA-specific. The form itself is intact and the four homography
  anchors are still visible; segmentation just can't assume the form is
  aligned with the page margins for this ~2 % of the corpus.

## Still open

- Scrape the transmisión portal (`divulgacione14presidentet....`) — the
  first-pass / on-night count, paired with our delegados corpus for
  fraud cross-checking. Similar size (~122 k actas). Lands under
  `data_2026/e14/transmision/` (per-portal subtree separation done).
- OCR / segmentation of the handwritten vote tallies. Layout reference:
  `e14-form-layout.md`.
