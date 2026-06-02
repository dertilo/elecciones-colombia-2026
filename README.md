# elecciones-colombia-2026

Code and notes around the 2026 Colombian elections — starting with the
presidential first round (May 31, 2026) and the E-14 *acta* PDFs published by
the Registraduría Nacional.

## What's here

- `scrape_2026_e14.py` — downloader for the E-14 PDFs from the
  `divulgacione14presidente.registraduria.gov.co` endpoints. Scraper
  gotchas (tee buffering, warn/fail counting, manual-retry drift) live in
  the module docstring.
- `docs/registraduria-e14-architecture.md` — architecture reference:
  static-JSON endpoints, URL pattern, code mapping, status 3 vs 11,
  GraphQL/Cognito fallback.
- `docs/scrape-2026-findings.md` — empirical results of the 2026-06-02
  full scrape (timing, error patterns, size distribution).
- `docs/e14-form-layout.md` — visual structure of the PDF *actas*: the
  two templates (regular + consulado), per-page contents, anchor points
  for geometric segmentation.

## What's not in git

The actual data lives under `data_2026/` and is **gitignored** because of size:

- `data_2026/e14/{portal}/**/*.pdf` — the per-mesa PDFs. `{portal}` is
  `delegados` or `transmision`; each portal has its own subtree so the
  two corpora never co-mingle. Delegados alone is ~22 GB / ~122 k actas
  (status 3 + 11).
- `data_2026/e14/{portal}/_index.json` — ~38 MB national status index
  (cached copy of `allTransmissionCodes.json`).
- `data_2026/e14/{portal}/_manifest.jsonl` — ~26 MB per-PDF manifest;
  rebuilt deterministically by the scraper from disk + the index.

If you clone this repo on a new machine, re-run the scraper to repopulate.

## Setup

This project uses [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
uv run python scrape_2026_e14.py --help
```

## License / status

Work in progress, public for transparency. No license file yet — ask before
reusing.
