# Historical Colombian election data — where the per-mesa numbers live

Companion to `registraduria-e14-architecture.md`, which covers the 2026
portals. This note records what is and is not available for **past**
elections (2018, 2022, …) when the goal is **per-mesa vote counts**
(tabular), not the E-14 acta PDFs.

## Where do per-mesa 2022 presidential vote counts live?

**Short answer: MOE (Misión de Observación Electoral) republished them.**
The Registraduría supplied MOE with the underlying mesa-level escrutinio
databases as part of its electoral-observation cooperation, and MOE
posted them as downloadable spreadsheets on `moe.org.co`. First-round
files are still live as direct `wp-content/uploads/` xlsx; second-round
files were Google Sheets that have since been deleted (HTTP 410). See
"Recovering the 2nd-round files" below for fallback paths.

This is the path. Every direct Registraduría endpoint is dead, but the
data itself is preserved.

### What MOE published

| Round | Type | Source URL | Size | Status |
|---|---|---|---|---|
| 1ra vuelta | Preconteo "primer avance" (cut-off 2022-06-01) | `https://www.moe.org.co/wp-content/uploads/2022/06/Escrutinios-primera-vuelta-presidencial-mesa-a-mesa-1.xlsx` | 8.4 MB | live |
| 1ra vuelta | CNE definitive escrutinio | `https://www.moe.org.co/wp-content/uploads/2022/06/Escrutinio-definitivo-1ra-vuelta-presidencial-2022.xlsx` | 8.6 MB | live |
| 2da vuelta | Preconteo at 99.99% mesas | `https://docs.google.com/spreadsheets/d/1LUladRfeuL8euCerXeYfR717hXi7-K6f/` | — | **410 Gone** |
| 2da vuelta | CNE definitive escrutinio | `https://docs.google.com/spreadsheets/d/1nG4yMvA4MSDIarZHYlokj_ZgioJ97SCg/` | — | **410 Gone** |

Posts that link these:
- `moe.org.co/datos-del-escrutinio-elecciones-presidenciales-2022-primera-vuelta-primer-avance-datos-con-corte-al-1-de-junio-de-2022/`
- `moe.org.co/datos-definitivos-del-escrutinio-elecciones-presidenciales-2022-primera-vuelta-resultados-definitivos-posteriores-al-escrutinio-general-a-cargo-del-consejo-nacional-electoral/`
- `moe.org.co/como-voto-la-ciudadania-colombiana-durante-la-segunda-vuelta-presidencial-datos-de-preconteo-con-un-avance-del-999/`
- `moe.org.co/datos-definitivos-del-escrutinio-elecciones-presidenciales-2022-segunda-vuelta-resultados-definitivos-declarados-por-el-consejo-nacional-electoral/`

### Schema (verified for 1ra vuelta)

Both 1ra-vuelta xlsx files share the same shape (~103,365 rows, 18 cols):

```
COD_DANE  Departamento  Municipio  Zona  Num_puesto  Puesto  Num_mesa
Sergio Fajardo  Federico Gutiérrez  Gustavo Petro  John Milton Rodríguez
Luis Pérez  Rodolfo Hernández  Enrique Gómez  Ingrid Betancourt
VOTOS EN BLANCO  VOTOS NO MARCADOS  VOTOS NULOS
```

`COD_DANE` is the 5-digit DIVIPOLA municipal code. `Zona` + `Num_puesto`
+ `Num_mesa` uniquely identify a polling table within the municipality.
The CNE-definitivo file has ~4 extra rows over the primer-avance file
(late-counted mesas).

### Recovering the 2nd-round files

Both Google Sheets return `410 Gone` — they were deleted from the
owner's Drive after publication. Recovery options, in increasing
order of effort:

1. **Wayback Machine** — Drive `/export?format=xlsx` URLs are sometimes
   archived. Query
   `https://web.archive.org/cdx/search/cdx?url=docs.google.com/spreadsheets/d/<ID>/*`
   for each ID. Note: `web.archive.org` is AWS-hosted and blocks many
   commercial-VPN exits with the same 919-byte CloudFront 403 the
   Registraduría serves; probe from a residential link or a clean
   exit.
2. **archive.today** — separate from Wayback, sometimes captures what
   Wayback misses. Query `https://archive.ph/https://docs.google.com/spreadsheets/d/<ID>/`.
3. **Other MOE artifacts** — the "Libro MOE: Resultados Electorales
   Congreso y Presidencia 2022"
   (`moe.org.co/libro-moe-resultados-electorales-congreso-y-presidencia-2022/`)
   may include the 2nd-round aggregates as PDF appendices. Not
   mesa-level but a useful sanity check.
4. **Email MOE directly** — `datoselectorales.org` invites data
   requests; the team that built the original xlsx likely still has
   the source files.
5. **Derecho de petición** to the Registraduría — the same data was
   given to MOE under a transparency obligation, so the RNEC is
   legally bound to produce it on request.

### Local download helper

`./download_moe_2022.sh [out_dir]` (defaults to
`data_2026/historical/2022_mesa_moe/`) re-pulls the live first-round
files and prints the dead 2nd-round URLs for the record. Output is
gitignored.

## Other historical sources surveyed

These came up in the same search pass; none is mesa-granular for 2022
but they are useful for cross-checking municipality-level totals or
for earlier elections.

- **CEDAE — Registraduría's open-data portal** —
  `cedae.registraduria.gov.co/datos-para-la-democracia/resultados-electorales/explora-datos`
  (mirror: `cedae.datasketch.co/datos-democracia/resultados-electorales/explora-los-datos/`).
  Advertises downloadable CSVs from 1958 to present for Presidencia,
  Congreso, Asamblea, Gobernación, Parlamento Andino, Alcaldía,
  Concejo. SPA front-end — granularity (mesa vs municipality) and the
  underlying download endpoints not yet probed. Likely municipality.
- **CEDE / Uniandes DataHub** — `doi:10.71590/R2KLKI` "Resultados
  Electorales de Colombia", 258 files spanning 1958-present. Stated
  granularity: *"desagregación municipal y por candidato"* — so
  municipality-level only, not mesa.
- **`estadisticaselectorales.registraduria.gov.co`** — interactive
  Registraduría dashboard that still serves 2022 second-round numbers
  through filterable tables with a download button. Live but not bulk-
  scrapable; mesa granularity unknown.

## What follows is the original dead-end inventory

Kept verbatim so the next investigator does not re-run the dead-host
search. The MOE path above supersedes it for the practical question
of getting the numbers.

### What were the actual 2022 hostnames?

From the Wayback CDX domain scan (`url=registraduria.gov.co
&matchType=domain`), the 2022 presidential election used **three**
distinct hosts — none of which we guessed initially:

- `divulgacione14presidencia.registraduria.gov.co` — 1st round E-14 PDFs.
- `divulgacione14presidencia2v.registraduria.gov.co` — 2nd vuelta E-14 PDFs.
- `eleccioncolombia.registraduria.gov.co` — candidate-info portal (`Conoce a tus candidatos`), with `/candidatos/getCandidatos`, `/candidatos/getPartidos`, `/config/election`, `/auth/csrf` etc.

All three are **NXDOMAIN today**. `divulgacione14.registraduria.gov.co`
(without the `presidencia` suffix) still resolves but `301`s to
`www.registraduria.gov.co`.

### Why is the 2022 architecture not scrapable like 2026?

It was a different stack. The E-14 portals were **jQuery + Bootstrap
3 + Akamai + reCAPTCHA v2**:

- Entry-point flow: `/auth/csrf` issues a token, then cascading
  `POST /selectCorp` → `/selectDepto` → `/selectMpio` → `/selectZona`
  → `/selectPto`, finally `/consultarE14` (with token +
  `g-recaptcha-response`) returns an HTML snippet, `/descargaE14`
  fetches the PDF.
- Every data call required the CSRF token plus a fresh reCAPTCHA
  solution, so even when the host was live, bulk scraping was
  significantly harder than 2026's open JSON manifests.
- The `eleccioncolombia.*` host was Akamai-protected — its CDX trail
  is full of `ak.*` bot-detection probe paths.

This matters mainly as a reminder: the 2026 scraper recipe does not
transfer to 2022 even if the hosts come back.

### Did the Wayback Machine save anything useful?

Only the static front-end. Across both E-14 hosts and
`eleccioncolombia.*`, Wayback captured the HTML root, CSS, fonts, and
the JS files (`consulta_1.js`, `functions.js`, obfuscated but with
plain endpoint strings) — all with status 200. But:

- Asset paths on `divulgacione14.registraduria.gov.co` (the pre-2022
  host) show status **400** in the CDX trail — the Wayback bot was
  blocked while crawling that older host.
- No XHR response (`/avancePais`, `/avanceDepto`, `/consultarE14`, …)
  was ever archived: they were `POST`-only and required a per-session
  CSRF token, so the bot never reached them.
- No mesa-level data file (JSON, CSV, Excel) was archived under any
  registraduria subdomain.

Worth keeping for forensic interest: the JS reveals the full backend
API surface, which would let someone reconstruct a scraper *if* the
hosts ever came back online (they won't).

### Is the data on `datos.gov.co`?

No. The Socrata catalog series **"Elecciones Presidenciales por
Municipio"** exists for 1990–2014 — **per-municipio only, stops at
2014**. No 2018 or 2022 presidential dataset, no `preconteo` or
`escrutinio` dataset at any granularity.

### Are there civic-society, academic, or third-party mirrors?

None found. Searched:

- Perplexity (`sonar-pro`) for civic-org / academic mirrors — empty;
  citations are all generic Wikipedia / EU-EOM summaries, nothing
  dataset-level.
- GitHub repos and code search (~30 Spanish/English query variants
  including candidate names, column names, file extensions).
- Kaggle, HDX (Humanitarian Data Exchange), Zenodo, Harvard Dataverse.

One Dataverse hit looked perfect by title — `doi:10.7910/DVN/CXKYAB`
"Replication Data for: La mesa más predictiva" by Kenneth Bunker — but
on inspection: 42,886 rows × 39 cols, 8 candidate columns
(`c1..c8`), published 2020. That's **Chilean** (~43k mesas, 8 candidates
in 2017 Chile), not Colombian. Author is Chilean (Tresquintos firm).
False positive.

### Did anything survive under `www.registraduria.gov.co` subpaths?

No. The `historico-de-resultados.html` page is **404**, and **every
unknown path under the entire registraduria.gov.co tree now serves the
2026 SPA shell as a 403** (34,614-byte HTML, title "Elección de
presidente y vicepresidente … 2026"). Probed paths included
`/elec2022/presidente/preconteo_mesamesa.htm`,
`/elec2022/presidente1v/`, `/elecciones_anteriores/2022PR/`,
`/escrutinios/presidente_cand_mpio` — all 403 with the SPA shell.

The 2010 preconteo path (`elec2010/presidente/preconteo_mesamesa.htm`)
*does* still show 200 in the Wayback CDX, suggesting the same `/elec{year}/`
pattern was used in 2022, but the actual content is no longer hosted.

## What lateral 2026 hostnames came out of this dig?

Reading the live 2026 SPA at `registraduria.gov.co/` revealed the full
2026 portal map (linked from the home page's "Resultados" section):

| Portal | Host |
|---|---|
| Preconteo (election-night counts) | `resultados.registraduria.gov.co` |
| **Escrutinios (official certified count)** | `escrutiniospresidente2026.registraduria.gov.co` |
| E-14 actas delegados | `divulgacione14presidente.registraduria.gov.co` |
| E-14 actas transmisión | `divulgacione14presidentet.registraduria.gov.co` |

`escrutiniospresidente2026.*` was new (not in
`registraduria-e14-architecture.md`). If it follows the 2026 pattern,
it should serve per-mesa numbers as JSON — which would make the OCR
pipeline a cross-check rather than the primary source of numbers.
**Not yet probed; next reconnaissance target.**

## Operational: AWS WAF blocks many origins from registraduria.gov.co

`resultados.registraduria.gov.co` (and other AWS-WAF-fronted
Registraduría hosts) returns a uniform **919-byte CloudFront "Request
blocked" 403** to traffic from a wide range of commercial-VPN exits
and cloud-provider ranges. The block is **not geographic** — the same
`curl_cffi` / Playwright probe that gets a 403 from a flagged origin
gets HTTP 200 from a residential link to the same destination. The
block is almost certainly AWS WAF's "Anonymous IP List" managed rule,
which flags commercial-VPN / hosting-provider ranges regardless of
country.

`web.archive.org` and `www.datos.gov.co` (both AWS US-East-1) exhibit
the same pattern from flagged exits.

Workaround at runtime: probe (or scrape) from an IP the WAF accepts.
A residential ISP works; mobile-tethered connections work; small
boutique VPS providers sometimes work. `scrape_preconteo.py` accepts
a `--ssh-host HOST` flag that bounces all its `curl`s through an SSH
alias so you can keep your workstation's VPN up while still hitting
the data.
