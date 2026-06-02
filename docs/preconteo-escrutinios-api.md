# 2026 Preconteo & Escrutinios — JSON API reverse-engineering

Companion to `registraduria-e14-architecture.md` (which covers the
**E-14 acta PDF** portals). This note covers the *numerical* data
portals — `resultados.registraduria.gov.co` (preconteo) and
`escrutiniospresidente2026.registraduria.gov.co` (escrutinios) — and
what granularity they expose.

## TL;DR

- The preconteo portal is a Vite + React SPA hosted on CloudFront.
  It exposes everything as **static JSON files** under `/json/...`
  with no auth, no CSRF, no fingerprint check — same model as the
  E-14 portals.
- Aggregates are exposed **only down to MUNICIPALITY level** (5-digit
  scope code, e.g. `60001` = Leticia). Zona / puesto / mesa are not
  exposed as separate JSONs (404). **Per-mesa numbers still require
  OCR of the E-14 PDFs.**
- Each municipality JSON embeds a `historico` array — the **full
  time-series** of avances since polls closed, pre-computed. No need
  to walk a `getHist` endpoint.
- The escrutinios portal `escrutiniospresidente2026.registraduria.gov.co`
  is on a **different CDN** (Nexusguard AP region, not CloudFront) and
  is currently unreachable (TCP timeout) — probably not yet active
  (escrutinios is the post-preconteo certified count) or geo-restricted.
  **Not yet probed; revisit after preconteo settles.**

## Preconteo portal: `resultados.registraduria.gov.co`

### Stack

- CloudFront (`d3u4pyzxb2h4gd.cloudfront.net`)
- Vite-built React SPA, single `/assets/index-DF8P2NjY.js` bundle (~1.4 MB)
- Tanstack Query for data fetching, all `cache: "no-store"`
- Polling every 5000 ms (from `/json/web/config.json`)

### Static configuration files

| Path | Purpose |
|---|---|
| `/json/web/config.json` | App-level config: polling interval, current avance number, "isOpen" flag, etc. |
| `/json/nomenclator.json` | 131 KB — the **complete geographic taxonomy**: all departments, all municipalities, hierarchy levels 1–7 (COLOMBIA→DEPARTAMENTO→MUNICIPIO→ZONA→COMUNA→PUESTO→MESA). Codes here (e.g. AMAZONAS = `60`, ANTIOQUIA = `01`) are what plug into the data endpoints. |
| `/json/notification.json` | Tiny: `{"PR": {"version": 7, "mdhm": "05311638"}}` — cache-busting pointer to current data version. SPA polls this and reloads everything else when `mdhm` advances. |

### Data endpoints (path templates from minified JS)

| Method name in JS | URL template | Status |
|---|---|---|
| `getScopeAct` | `/json/ACT/:electionSiglas/:scopeCode.json` | **Works** — main endpoint. |
| `getHome` | `/json/INI/:electionSiglas/IN_:scopeCode.json` | 403 from CloudFront (separate ACL — possibly Origin-locked). |
| `getHist` | `/json/HIST/:departmentCode/:electionSiglas/:advance/:scopeCode.json` | 403 from CloudFront (same — likely needs the live Origin/Referer header). |
| `getStat` | `/json/EST/:electionSiglas/EST_:statCode.json` | not yet probed. |
| `getElectoralStructure` | `/json/nomenclator.json` | works. |
| `getNotification` | `/json/notification.json` | works. |

`electionSiglas` is `"PR"` for the 2026 presidential election (from
the nomenclator's `elec[].sigla`).

### Scope-code hierarchy

| Level | Code length | Example | Notes |
|---|---|---|---|
| Nacional | 2 digits | `00` | Colombia rollup |
| Departamento | 2 digits | `60` (Amazonas), `01` (Antioquia) | From nomenclator `amb[].co` field |
| Municipio | 5 digits | `60001` (Leticia) | `dept(2) + muni(3)` concatenated |
| Zona / Puesto / Mesa | – | – | **Not exposed.** Confirmed: 6-, 7-, 8-, 9-, 10-digit scope codes all return 404. |

So `getScopeAct` returns aggregates at three levels only: country,
department, municipality. The municipality JSON does not contain its
constituent mesas.

### Shape of an `ACT` JSON

Verified against `https://resultados.registraduria.gov.co/json/ACT/PR/60001.json`
(Leticia, 6.7 KB):

```
elec, amb, dept, tope, numact, numdep, iscircus, mdhm, shc
totales.act
  metota          # total mesas
  mesesc          # mesas escrutadas
  pmesesc         # pct escrutadas, e.g. "100%"
  centota         # censo electoral
  votant, pvotant # votantes (count and %)
  absten, pabsten # abstención
  votnul, pvotnul # nulos
  votnma, pvotnma # no marcados
  votblan, pvotblan
  votval, pvotval
camaras[]
  cam, cir, ...
  totales.act { vot* aggregated for this cámara }
  partotabla[]                  # one entry per party
    act
      codpar, vot, pvot
      cantotabla[]              # candidates within party
        codcan, sorteo, cedula
        nomcan, apecan, nomcan2, apecan2
        vot, pvot, pref
  mapagan[]                     # winner map by sub-territory (empty at muni)
historico[]                     # ~15 snapshots
  numact, numdep, mesesc, mesfalt, mdhm, pvotant
dept
```

`mdhm` is the snapshot timestamp encoded as `MMDDHHMM` (no year, no
seconds, no separators) — e.g. `"05311803"` = May 31, 18:03.

### Live data on 2026-06-02 (post-election)

Election day was 2026-05-31. As of probe time, the country JSON
reports:

- **122,020 mesas** total, **121,566 reported** (99.62% pmesesc)
- **23,911,588** votantes (57.72% turnout)
- Leading candidates in the SPA's `partotabla`:
  - **ABELARDO DE LA ESPRIELLA** / JOSÉ MANUEL RESTREPO ABONDANO — 10.33 M votes (43.73%)
  - **IVÁN CEPEDA CASTRO** / AIDA MARINA QUILCUE VIVAS — 9.66 M votes (40.91%)

(Numbers and candidate IDs are surfaced for record-keeping; not yet
sanity-checked against an external source.)

### Implications for the project

- **A municipality-level live time-series is free.** Pulling all
  ~1,100 municipality JSONs is ~1 GB max and gives both the latest
  aggregate and the full intra-day history of avances.
- **Per-mesa numbers are *not* in this portal.** The OCR pipeline
  remains the primary path to mesa-level data — same conclusion as
  before, just now confirmed by inspection rather than assumed.
- **The preconteo aggregates are a perfect OCR cross-check.** Once a
  batch of E-14s is OCR'd for a given municipality, summing them
  should match `totales.act.votant` / `partotabla[*].vot` in the
  corresponding `/json/ACT/PR/XXXXX.json`. Any mismatch is either an
  OCR error or a fraud signal.

### Snapshot scraper: `scrape_preconteo.py`

Repo-root script that takes one full preconteo snapshot per
invocation. No scheduler — run manually (or wire up cron later).

What it does:

1. Pulls `/json/nomenclator.json`, parses `amb[0].ambitos[]`, collects
   every scope code at levels 1–3 (~1 country + ~33 depts + ~1,100
   munis ≈ 1,135 codes total).
2. Fetches each `/json/ACT/PR/{co}.json` either locally or — if
   `--ssh-host HOST` is given — by opening a **single SSH session** to
   `HOST`, looping `curl` on the remote side into a tmpdir, then
   `rsync`ing back. The SSH passthrough exists because `resultados.*`
   is fronted by AWS WAF, which serves CloudFront 403 to many cloud
   and commercial-VPN IP ranges; if your direct IP is blocked, pass a
   jump host whose origin IP passes the WAF.
3. Writes `data_2026/preconteo/{YYYY-MM-DDTHH-MM-SSZ}/`:
   - `nomenclator.json` — frozen copy of the scope directory
   - `{co}.json` — one file per scope, flat (`00.json`, `05.json`,
     `05001.json`, …)
   - `status.txt` — one `HTTP_CODE co` line per request
   - `_index.json` — run timestamp, counts, HTTP-status histogram,
     failed codes, and the top-level `totales` block from `00.json`
     so the index is human-glanceable

Polite defaults: `--sleep 0.15` between curls (≈3 min total for a full
run). Use `--dry-run` to list codes without fetching.

First snapshot (`2026-06-02T08-56-50Z`): all 1,224 requests returned
HTTP 200, 11 MB total. National roll-up captured: 121,566 / 122,020
mesas (99.62%), 23.9 M voters, 57.72% turnout.

The output directory lives under `data_2026/` which is gitignored —
snapshots accumulate locally and are never committed. The `_index.json`
files make it easy to diff totals between snapshots later without
parsing the full muni corpus.

## Escrutinios portal: `escrutiniospresidente2026.registraduria.gov.co`

Currently **unreachable** (TCP timeout from every origin tried so far
— CO-via-VPN exits and DE residential alike).

DNS resolves to `27.126.250.121` — **Nexusguard AP-DSR**
(`18239150286811f-cdd.ap-dsr.nexusguard.cloud`), an Asia-Pacific
anti-DDoS CDN, not CloudFront. The hostname pattern `…2026…`
suggests a dedicated stack provisioned per election cycle.

Three hypotheses, in rough order of likelihood:

1. **Not yet active.** Escrutinios is the *certified* count and
   legally happens days/weeks *after* preconteo. The portal may not
   be flipped on yet.
2. **Geo-restricted to CO origin IPs.** Nexusguard's AP edges can
   enforce country ACLs.
3. **Awaiting CDN warm-up / DNS propagation.** Unlikely given
   resolvability.

Nothing more to do here until either the portal opens or someone
inside Colombia can confirm reachability. The reconnaissance
template (pull the JS bundle, grep for `path:"/json/.../"` route
definitions) transfers directly once it does.

## Operational reminders

- `getHome` (`/json/INI/PR/IN_*.json`) and `getHist`
  (`/json/HIST/...`) both return CloudFront 403 (919-byte HTML, the
  generic "Request blocked"). The SPA can fetch them in-browser, so
  the block is likely keyed on `Origin` / `Referer` header presence,
  not on IP. Worth retrying with browser-faithful headers if these
  endpoints turn out to matter.
- The AWS-WAF block documented in
  `historical-elections-data-sources.md` applies here too:
  `resultados.*` is fronted by CloudFront and rejects many cloud and
  commercial-VPN IP ranges. From a blocked origin, route probes
  through `scrape_preconteo.py --ssh-host HOST` or any equivalent
  SSH-jump to an IP the WAF accepts.
