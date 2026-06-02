"""Scraper for the 2026 E-14 presidential actas from the Registraduría.

Architecture reference: see `docs/registraduria-e14-architecture.md`. Short
version: every mesa->PDF mapping lives in one static JSON
(`allTransmissionCodes.json`, ~6 MB). Each PDF URL is deterministically
derivable. No browser, no auth, no Cognito needed.

Defaults are intentionally polite:
  * concurrency = 2
  * delay-ms    = 300 (per worker, additive with jitter)
  * limit       = 10 (sanity-check mode; pass `--limit 0` for a full run)
  * retry       = 5x with exponential backoff on 429 / 5xx

Gotchas observed in real runs:
  * Live progress: do not tail a `tee`-ed log file. Python buffers stdout
    through the pipe in large blocks, so the file stays empty for minutes.
    Use `tmux attach`, or poll the manifest line count.
  * Transport timeouts that exhaust `max_retries` are counted as `fail=N`
    in the final summary but only emit `[warn]` lines, never `[fail]`.
    Only HTTP errors trigger `[fail]`. -> `grep '^[fail]'` misses
    timeout-failures; look for mesas with `>= max_retries` `[warn]`
    entries instead.
  * A manual retry via direct `curl_cffi` (instead of re-running this
    script) writes **no** manifest entry. Manifest and disk state drift
    apart by the retry count. Disk is the ground truth, manifest is a
    byproduct.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from curl_cffi import requests as curlreq
from curl_cffi.requests import AsyncSession

# ---- Endpoints ----------------------------------------------------------------

# Title block of the PDFs verifies the mapping (2026-06-02):
#   no-t host  -> "DELEGADOS"   (second-pass, verified count)
#   with-t host -> "TRANSMISIÓN" (on-night first-pass count)
PORTAL_HOSTS = {
    "delegados":   "divulgacione14presidente.registraduria.gov.co",
    "transmision": "divulgacione14presidentet.registraduria.gov.co",
}
TRANSMISSION_CODES_PATH = "/assets/temis/divipol_json/allTransmissionCodes.json"
PDF_PATH_TPL = "/assets/temis/pdf/{dep}/{mun}/{zon}/{sub}/{mesa}/PRE/{name}"

# curl_cffi's `impersonate=` aligns User-Agent, Accept-*, TLS fingerprint and
# HTTP/2 frame order so that Akamai does not score the connection as a bot.
IMPERSONATE = "chrome"
EXTRA_HEADERS = {
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
}

# ---- Data types ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MesaRecord:
    dep: str          # 2 digits
    mun: str          # 3 digits
    zon: str          # 3 digits (URL variant)
    sub: str          # 2 digits (puesto)
    mesa: str         # 3 digits
    name: str         # expectedName, including .pdf
    status: int       # 3 or 11

    @property
    def url_path(self) -> str:
        return PDF_PATH_TPL.format(
            dep=self.dep, mun=self.mun, zon=self.zon,
            sub=self.sub, mesa=self.mesa, name=self.name,
        )

    @property
    def local_relpath(self) -> str:
        # Flat per-mesa hierarchy; the hash stays in the filename.
        return f"{self.dep}/{self.mun}/{self.zon}/{self.sub}/{self.mesa}_{self.name}"


def _norm(record: dict) -> MesaRecord:
    """Padding mirrors `normalizeCodes` in the frontend (chunk-QBZORZXG.js)."""
    return MesaRecord(
        dep=str(record["idDepartmentCode"]).zfill(2),
        mun=str(record["municipalityCode"]).zfill(3),
        zon=str(record["idZoneCode"]).zfill(3),
        sub=str(record["standCode"]).zfill(2),
        mesa=str(record["numberStand"]).zfill(3),
        name=record["expectedName"],
        status=int(record["idTransmissionCodeStatus"]),
    )


# ---- Load index ---------------------------------------------------------------

async def load_index(client: AsyncSession, host: str, cache: Path) -> list[MesaRecord]:
    if cache.exists():
        raw = json.loads(cache.read_text())
        print(f"[index] cache hit: {cache} ({cache.stat().st_size/1e6:.1f} MB)")
    else:
        url = f"https://{host}{TRANSMISSION_CODES_PATH}?uuid={random.randint(0, 10**12)}"
        print(f"[index] fetching {url}")
        r = await client.get(url, timeout=120)
        r.raise_for_status()
        raw = r.json()
        cache.write_text(json.dumps(raw))
        print(f"[index] cached -> {cache} ({cache.stat().st_size/1e6:.1f} MB)")
    nodes = raw["data"]["status3"]["nodes"] + raw["data"]["status11"]["nodes"]
    return [_norm(n) for n in nodes]


# ---- Download loop ------------------------------------------------------------

async def fetch_one(
    client: AsyncSession,
    host: str,
    mesa: MesaRecord,
    out_dir: Path,
    delay_ms: int,
    max_retries: int,
) -> tuple[MesaRecord, str, int]:
    """Returns (mesa, status, bytes). status in {'ok','skip','fail'}."""
    target = out_dir / mesa.local_relpath
    if target.exists() and target.stat().st_size > 0:
        return mesa, "skip", target.stat().st_size

    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://{host}{mesa.url_path}?uuid={random.randint(0, 10**12)}"

    for attempt in range(1, max_retries + 1):
        try:
            r = await client.get(url, timeout=60)
        except curlreq.errors.RequestsError as e:
            sleep = min(30, 2 ** attempt) + random.random()
            print(f"[warn] {mesa.name} transport error ({e!r}); retry in {sleep:.1f}s")
            await asyncio.sleep(sleep)
            continue

        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"):
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.rename(target)
            await asyncio.sleep((delay_ms / 1000.0) * (0.5 + random.random()))
            return mesa, "ok", len(r.content)

        if r.status_code in (0, 429, 500, 502, 503, 504):
            sleep = min(60, 2 ** attempt) + random.random()
            print(f"[warn] {mesa.name} HTTP {r.status_code}; backoff {sleep:.1f}s (try {attempt}/{max_retries})")
            await asyncio.sleep(sleep)
            continue

        print(f"[fail] {mesa.name} HTTP {r.status_code} ct={r.headers.get('content-type')}")
        return mesa, "fail", 0

    return mesa, "fail", 0


async def run(args: argparse.Namespace) -> int:
    host = PORTAL_HOSTS[args.portal]
    # Each portal's corpus lives in its own subtree so the two never co-mingle.
    out_dir = Path(args.output_dir).expanduser() / args.portal
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "_index.json"
    manifest = out_dir / "_manifest.jsonl"

    async with AsyncSession(impersonate=IMPERSONATE, headers=EXTRA_HEADERS) as client:
        records = await load_index(client, host, cache)
        print(f"[index] {len(records)} mesas total "
              f"({sum(1 for r in records if r.status == 11)} status-11, "
              f"{sum(1 for r in records if r.status == 3)} status-3)")

        if args.status != "both":
            wanted = int(args.status)
            records = [r for r in records if r.status == wanted]
            print(f"[filter] keeping status={wanted}: {len(records)} records")

        if args.shuffle:
            random.shuffle(records)

        if args.limit > 0:
            records = records[: args.limit]
            print(f"[limit] truncated to first {len(records)}")

        sem = asyncio.Semaphore(args.concurrency)
        t0 = time.monotonic()
        counts = {"ok": 0, "skip": 0, "fail": 0}
        total_bytes = 0
        manifest_fh = manifest.open("a")

        async def bounded(rec: MesaRecord) -> None:
            nonlocal total_bytes
            async with sem:
                mesa, status, n = await fetch_one(
                    client, host, rec, out_dir,
                    delay_ms=args.delay_ms,
                    max_retries=args.max_retries,
                )
            counts[status] += 1
            total_bytes += n
            if status == "ok":
                manifest_fh.write(json.dumps({
                    "mesa": asdict(mesa),
                    "bytes": n,
                    "ts": time.time(),
                }) + "\n")
                manifest_fh.flush()
            done = sum(counts.values())
            if done % 10 == 0 or done == len(records):
                dt = time.monotonic() - t0
                rate = done / dt if dt else 0
                print(f"[{done}/{len(records)}] ok={counts['ok']} skip={counts['skip']} "
                      f"fail={counts['fail']} | {total_bytes/1e6:.1f} MB | {rate:.1f} req/s")

        try:
            await asyncio.gather(*(bounded(r) for r in records))
        finally:
            manifest_fh.close()

        print(f"[done] {counts} bytes={total_bytes/1e6:.1f} MB in {time.monotonic()-t0:.1f}s")
        return 0 if counts["fail"] == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--portal", choices=PORTAL_HOSTS.keys(), default="delegados",
                   help="Which portal to scrape. Default matches the corpus already on disk.")
    p.add_argument("--output-dir", default="./data_2026/e14")
    p.add_argument("--limit", type=int, default=10,
                   help="Max mesas to fetch this run (0 = no limit). Default 10 for sanity check.")
    p.add_argument("--status", choices=["3", "11", "both"], default="both")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--delay-ms", type=int, default=300,
                   help="Mean sleep between requests per worker (50%% jitter).")
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--shuffle", action="store_true",
                   help="Shuffle index before truncating with --limit (spreads sample across the country).")
    args = p.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[abort] user interrupt")
        return 130


if __name__ == "__main__":
    sys.exit(main())
