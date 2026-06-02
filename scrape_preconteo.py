"""Snapshot scraper for the 2026 Colombian presidential preconteo.

Architecture reference: docs/preconteo-escrutinios-api.md.

Quick facts:
  * resultados.registraduria.gov.co is CloudFront-backed and protected
    by AWS WAF, which rejects many cloud and commercial-VPN IP ranges
    with a 919-byte "Request blocked" 403.  From a blocked origin, pass
    `--ssh-host HOST` to bounce the curls through an SSH alias whose
    IP isn't on the WAF anonymous list.  The single SSH session runs the
    whole loop remotely (no per-request SSH overhead) and rsyncs the
    results back at the end.
  * Three geographic levels are exposed:
        l=1  country   code "00"         (1 scope)
        l=2  dept      2-digit codes     (~33 scopes)
        l=3  muni      5-digit codes     (~1100 scopes)
    Finer levels (zona / puesto / mesa) return 404.
  * Scope-code directory: GET /json/nomenclator.json → amb[0].ambitos[].
    Each item has `co` (scope code) and `l` (level).
  * Vote data per scope: GET /json/ACT/PR/{co}.json.
  * Municipality JSONs embed a `historico` array (full intra-day time-series),
    so a single snapshot already captures the evolution of the count.

Outputs (data_2026/preconteo/<YYYY-MM-DDTHH-MM-SSZ>/):
  nomenclator.json    copy of the scope directory (131 KB)
  {co}.json           one file per scope, e.g. 00.json / 05.json / 05001.json
  status.txt          one "HTTP_CODE co" line per request, for debugging
  _index.json         run metadata: timestamp, counts, HTTP histogram,
                      failed codes, and top-level totales from 00.json

Usage:
  python scrape_preconteo.py                        # run locally (if IP not blocked)
  python scrape_preconteo.py --ssh-host myhost      # bounce through SSH alias
  python scrape_preconteo.py --dry-run              # list codes, no fetching
  python scrape_preconteo.py --sleep 0.3            # slower / more polite

Polite defaults:
  --sleep 0.15   seconds between curl requests (on whichever host is running
                 curl); total for ~1135 codes ≈ 3 min just sleeping.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "https://resultados.registraduria.gov.co"
DEFAULT_DATA_ROOT = Path("data_2026/preconteo")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# ── Shell runners ──────────────────────────────────────────────────────────────

# A runner is a callable (script: str, **subprocess_kwargs) → CompletedProcess.
# It abstracts "run this bash script" — locally or via SSH — so the fetch
# logic is identical in both modes.


def make_ssh_runner(ssh_host: str):
    """Return a runner that executes bash scripts on *ssh_host* via stdin."""
    def run(script: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh", ssh_host, "bash"],
            input=script, text=True, **kwargs,
        )
    return run


def make_local_runner():
    """Return a runner that executes bash scripts in the local shell via stdin."""
    def run(script: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash"],
            input=script, text=True, **kwargs,
        )
    return run


# ── Nomenclator ────────────────────────────────────────────────────────────────


def fetch_nomenclator(runner) -> dict:
    """Fetch /json/nomenclator.json via *runner*, return parsed dict."""
    url = f"{BASE_URL}/json/nomenclator.json"
    r = runner(
        f"curl -fsSL --max-time 30 -A {shlex.quote(USER_AGENT)} {shlex.quote(url)}",
        capture_output=True, check=True,
    )
    return json.loads(r.stdout)


def parse_scopes(nom: dict) -> list[dict]:
    """Return [{co, l}, …] for levels 1–3 in their natural order."""
    items = nom["amb"][0]["ambitos"]
    return [{"co": item["co"], "l": item["l"]} for item in items if item["l"] in {1, 2, 3}]


# ── Fetch loop ─────────────────────────────────────────────────────────────────


def fetch_all(
    runner,
    codes: list[str],
    target_dir: str,
    sleep_s: float,
) -> None:
    """
    Run a single bash session via *runner* that:
      1. Creates *target_dir*.
      2. Curls /json/ACT/PR/{co}.json for every code into target_dir/{co}.json.
      3. Writes one "HTTP_CODE co" line per request to target_dir/status.txt.

    Tolerates non-200 responses and network errors — both produce a status line
    (the real HTTP code, or "000" for connection/timeout failures) so the index
    builder can always account for every code.
    """
    # Embed the codes list as a printf argument list inside the script itself
    # to avoid stdin conflicts (the script is already read from stdin).
    codes_args = " ".join(shlex.quote(co) for co in codes)

    # f-string quoting note:
    #   {{...}} → literal {…}  so ${co} and %{http_code} reach bash/curl intact.
    #   \\n     → \n           which curl -w interprets as a newline.
    script = f"""\
RDIR={shlex.quote(target_dir)}
mkdir -p "$RDIR"
cd "$RDIR"

printf '%s\\n' {codes_args} > codes.txt

echo "[curl] loop for {len(codes)} codes, sleep {sleep_s}s each" >&2

while IFS= read -r co; do
  curl -sS --max-time 20 \\
    -A {shlex.quote(USER_AGENT)} \\
    "{BASE_URL}/json/ACT/PR/${{co}}.json" \\
    -o "${{co}}.json" \\
    -w "%{{http_code}} ${{co}}\\n" || printf "000 %s\\n" "$co"
  sleep {sleep_s}
done < codes.txt > status.txt

echo "[curl] done — $(wc -l < status.txt) lines in status.txt" >&2
"""
    runner(script, check=True)


# ── rsync + cleanup (SSH mode only) ───────────────────────────────────────────


def rsync_back(ssh_host: str, remote_dir: str, local_dir: Path) -> None:
    """rsync remote_dir/ → local_dir/ (used in SSH mode only)."""
    local_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["rsync", "-a", f"{ssh_host}:{remote_dir}/", f"{local_dir}/"],
        check=True,
    )


def cleanup_remote(runner, remote_dir: str) -> None:
    """Remove the remote tmpdir (best-effort, never aborts the run)."""
    runner(f"rm -rf {shlex.quote(remote_dir)}", check=False)


# ── Index building ─────────────────────────────────────────────────────────────


def build_index(
    local_dir: Path,
    scopes: list[dict],
    ts_utc: str,
) -> dict:
    """
    Read status.txt and 00.json from *local_dir*, build the _index.json dict.
    Returns a dict even if data files are missing (records warnings instead).
    """
    # Parse status.txt ─ one "HTTP_CODE co" line per request
    status_path = local_dir / "status.txt"
    code_status: dict[str, int] = {}
    if status_path.exists():
        for raw_line in status_path.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    code_status[parts[1]] = int(parts[0])
                except ValueError:
                    pass
    else:
        print("[warn] status.txt not found; HTTP histogram will be empty", flush=True)

    histogram: dict[str, int] = {
        str(k): v for k, v in sorted(Counter(code_status.values()).items())
    }
    failed_codes = sorted(co for co, st in code_status.items() if st != 200)

    # Pull totales from the national JSON
    totales_act = None
    nat_path = local_dir / "00.json"
    if nat_path.exists():
        try:
            nat = json.loads(nat_path.read_text())
            totales_act = nat.get("totales", {}).get("act")
        except Exception as exc:
            print(f"[warn] could not parse 00.json: {exc}", flush=True)
    else:
        print("[warn] 00.json not found; totales will be absent from index", flush=True)

    return {
        "run_ts": ts_utc,
        "scope_counts": {
            "country": sum(1 for s in scopes if s["l"] == 1),
            "dept":    sum(1 for s in scopes if s["l"] == 2),
            "muni":    sum(1 for s in scopes if s["l"] == 3),
            "total":   len(scopes),
        },
        "http_status_histogram": histogram,
        "failed_codes": failed_codes,
        "totales_act": totales_act,
    }


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print scope codes and exit without fetching anything.",
    )
    p.add_argument(
        "--sleep", type=float, default=0.15, metavar="SEC",
        help=(
            "Seconds to sleep between curl requests (on whichever host is "
            "running curl; default 0.15)."
        ),
    )
    p.add_argument(
        "--ssh-host", default=None, metavar="HOST",
        help=(
            "If your IP is blocked by the Registraduría's WAF, bounce all curls "
            "through this SSH alias.  Without this flag the script runs curl locally."
        ),
    )
    p.add_argument(
        "--output-dir", default=str(DEFAULT_DATA_ROOT), metavar="DIR",
        help=f"Root output directory (default: {DEFAULT_DATA_ROOT}).",
    )
    args = p.parse_args()

    ssh_host: str | None = args.ssh_host
    use_ssh = ssh_host is not None

    # Pick the appropriate shell runner
    runner = make_ssh_runner(ssh_host) if use_ssh else make_local_runner()

    # Timestamp for this snapshot (used in both the local path and _index.json)
    now = datetime.now(timezone.utc)
    ts_utc = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    snap_dir = Path(args.output_dir) / ts_utc

    # ── 1. Fetch & parse nomenclator ──────────────────────────────────────────
    if use_ssh:
        print(f"[nomenclator] fetching via {ssh_host} …", flush=True)
    else:
        print("[nomenclator] fetching locally …", flush=True)
    try:
        nom = fetch_nomenclator(runner)
    except subprocess.CalledProcessError as exc:
        print(f"[error] could not fetch nomenclator: {exc}", flush=True)
        return 1

    scopes = parse_scopes(nom)
    codes = [s["co"] for s in scopes]

    n_country = sum(1 for s in scopes if s["l"] == 1)
    n_dept    = sum(1 for s in scopes if s["l"] == 2)
    n_muni    = sum(1 for s in scopes if s["l"] == 3)
    print(
        f"[scopes] {len(codes)} total — "
        f"{n_country} country, {n_dept} dept, {n_muni} muni",
        flush=True,
    )

    # ── Dry-run early exit ────────────────────────────────────────────────────
    if args.dry_run:
        level_name = {1: "country", 2: "dept", 3: "muni"}
        print("[dry-run] scope codes:")
        for s in scopes:
            print(f"  {s['co']:>5}  l={s['l']} ({level_name.get(s['l'], '?')})")
        return 0

    # ── 2. Create snapshot dir, save nomenclator ──────────────────────────────
    snap_dir.mkdir(parents=True, exist_ok=True)
    nom_path = snap_dir / "nomenclator.json"
    nom_path.write_text(json.dumps(nom, ensure_ascii=False, indent=2))
    print(f"[nomenclator] saved → {nom_path}", flush=True)

    # ── 3. Fetch loop ─────────────────────────────────────────────────────────
    est_sec = len(codes) * (args.sleep + 0.35)
    if use_ssh:
        # Run on remote host; rsync results back, then clean up
        remote_dir = f"/tmp/preconteo_{ts_utc}"
        print(
            f"[fetch] remote tmpdir : {ssh_host}:{remote_dir}\n"
            f"[fetch] sleep={args.sleep}s/req  estimated ≈{est_sec/60:.1f} min",
            flush=True,
        )
        try:
            fetch_all(runner, codes, remote_dir, args.sleep)
        except subprocess.CalledProcessError as exc:
            print(f"[error] SSH fetch loop failed (exit {exc.returncode})", flush=True)
            print("[warn] attempting partial rsync anyway …", flush=True)

        print(f"[rsync] {ssh_host}:{remote_dir}/ → {snap_dir}/", flush=True)
        try:
            rsync_back(ssh_host, remote_dir, snap_dir)
        except subprocess.CalledProcessError as exc:
            print(f"[error] rsync failed: {exc}", flush=True)
            return 1

        print(f"[cleanup] removing {ssh_host}:{remote_dir}", flush=True)
        cleanup_remote(runner, remote_dir)

    else:
        # Run locally; write directly into snap_dir (no rsync or cleanup needed)
        print(
            f"[fetch] writing to {snap_dir}\n"
            f"[fetch] sleep={args.sleep}s/req  estimated ≈{est_sec/60:.1f} min",
            flush=True,
        )
        try:
            fetch_all(runner, codes, str(snap_dir), args.sleep)
        except subprocess.CalledProcessError as exc:
            print(f"[error] local fetch loop failed (exit {exc.returncode})", flush=True)
            print("[warn] continuing with partial results …", flush=True)

    # ── 4. Build & write _index.json ──────────────────────────────────────────
    index = build_index(snap_dir, scopes, ts_utc)
    index_path = snap_dir / "_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(f"[index] wrote → {index_path}", flush=True)

    # ── 5. Summary ────────────────────────────────────────────────────────────
    hist = index["http_status_histogram"]
    tot  = index["totales_act"] or {}
    failed = index["failed_codes"]
    print(f"\n{'─'*64}")
    print(f"  snapshot  : {snap_dir}")
    print(f"  scopes    : {index['scope_counts']}")
    print(f"  HTTP hist : {hist}")
    if failed:
        print(f"  failed    : {failed}")
    if tot:
        mesesc  = tot.get("mesesc",  "?")
        metota  = tot.get("metota",  "?")
        pmesesc = tot.get("pmesesc", "?")
        votant  = tot.get("votant",  "?")
        pvotant = tot.get("pvotant", "?")
        centota = tot.get("centota", "?")
        print(f"  mesas     : {mesesc}/{metota} ({pmesesc})")
        print(f"  votantes  : {votant:,} ({pvotant})  [censo {centota:,}]"
              if isinstance(votant, int) and isinstance(centota, int)
              else f"  votantes  : {votant} ({pvotant})  [censo {centota}]")
    print(f"{'─'*64}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
