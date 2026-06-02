# Registraduría E-14 Portal 2026 — Architecture

Reference notes on how the two Registraduría portals expose the E-14
*actas* and how to fetch them without a browser. There are two parallel
corpora, served from near-identical hostnames, one differing by a
trailing `t`:

| Host | Corpus | Title block on each PDF |
|---|---|---|
| `divulgacione14presidente.registraduria.gov.co` | **Delegados** | `DELEGADOS` |
| `divulgacione14presidentet.registraduria.gov.co` | **Transmisión** | `TRANSMISIÓN` |

Verified 2026-06-02 by rendering one PDF per host and reading the title
block. Both hosts share the JSON layout, URL pattern, and anti-bot
behaviour described below. The two corpora are independent (different
`expectedName` hashes per mesa) and exist for fraud cross-checking:
transmisión is the on-night first-pass count, delegados is the verified
second-pass count.

## Where do the E-14 PDFs come from?

Direct HTTP GET — **no browser, no auth, no Cognito/SigV4 needed**. The
full mesa→PDF table is published as a single static JSON.

PDF URL pattern, per mesa (same on both hosts):

```
https://{host}/assets/temis/pdf/{dep2}/{mun3}/{zon3}/{sub2}/{mesa3}/PRE/{expectedName}?uuid={any}
```

Values come from `allTransmissionCodes.json` (see below). The `uuid` query
parameter is a cache-buster — any value works.

### `expectedName` rotates

The hash filename for a given mesa changes between publishes. A URL
that returned a PDF yesterday will today fall through to the Angular
SPA shell (Akamai's fallback to `index.html` when the requested asset
is missing) — `Content-Type: text/html`, ~1 KB. Always re-read the
JSON index before re-fetching; treat the manifest as a snapshot, not a
permanent address book.

## Where does the data live?

Three static endpoints — all unauthenticated, all reachable without geo
restriction. Set `Accept-Language` + `Accept-Encoding: gzip,deflate,br` and
curl `--compressed`, otherwise the Akamai WAF kills the HTTP/2 stream.

| Path | Content |
|---|---|
| `/assets/text/main.json` | App config. The flag `divipolSource: true` enables static-JSON mode. |
| `/assets/temis/divipol_json/departmentsTree.json` (~300 KB) | Full DIVIPOL hierarchy: 34 dep / 1 189 mun / 3 013 zonas / 14 438 puestos / 122 020 mesas. |
| `/assets/temis/divipol_json/allTransmissionCodes.json` (~6 MB) | **All published E-14s.** One entry per mesa, with `expectedName` (the PDF filename — a SHA-256 hash) and all location codes. |

`departmentsTree.json` alone only yields mesa *numbers*; the PDF filenames
come from `allTransmissionCodes.json`. If the `divipolSource` flag in
`main.json` is ever flipped to `false`, the frontend falls back to GraphQL
via AWS AppSync (see below).

`idTransmissionCodeStatus`: values `3` and `11`. **Not** "Transmisión vs.
Delegados" — an initial guess that turned out wrong. Status 11 covers the
~121.7 k regular mesas. Status 3 is 102 mesas with atypical vote patterns:
91 of them have `dep=88` (consulados), the rest sit in `zon=99` ("puestos
especiales": prisons, hospitals, itinerant) in rural departamentos. Same
form template, but the contents are sparse (often single-digit voter
counts, empty candidate columns). The two status sets are **disjoint by
mesa tuple** — no mesa appears in both. When aggregating, count them
together or split intentionally, but don't deduplicate.

## How to map the codes in `allTransmissionCodes.json`

Frontend logic from `chunk-QBZORZXG.js`, `normalizeCodes`:

| JSON field | URL segment | Padding |
|---|---|---|
| `idDepartmentCode` | `dep2` | 2 |
| `municipalityCode` | `mun3` | 3 |
| `idZoneCode` | `zon3` (URL) / `zon2` (in `idStand`) | 3 / 2 |
| `standCode` | `sub2` | 2 |
| `numberStand` | `mesa3` | 3 |
| `expectedName` | filename at end | — |

The `idStand` field is `${sub2}${zon2}${mun3}${dep2}` (9 digits) — the key
used in JSON mode to filter per puesto.

`PRE` is hard-coded as the acronym lookup for `idCorporationCode = "001"`
(Presidente, the only entry in `allCorporations.json`).

## Backend fallback (if the static JSONs ever disappear)

GraphQL endpoint with IAM auth via Cognito Identity Pool — **everything
extractable from the JS bundle**:

```
graphqlUrl   = https://apx2e14awsprodpresidencia.prdtpssas.com/graphql
identityPool = us-east-2:58326cd4-70d8-4b4c-bd34-adc55fa72dc3
region       = us-east-2
```

Two plain-JSON POSTs **unauthenticated** to
`cognito-identity.us-east-2.amazonaws.com`
(`AWSCognitoIdentityService.GetId` then `GetCredentialsForIdentity`) return
temporary AWS credentials — the reCAPTCHA site key baked into the bundle
is client-side only and not enforced by the backend. Credentials expire
after ~30 min; re-issuing is cheap. Sign the subsequent GraphQL POST with
SigV4 using these creds.

Relevant queries in the bundle (constants `Q_DEPARTMENTS_TREE`,
`Q_TRANSMISSION_CODES_BY_STAND`, etc., in `chunk-QBZORZXG.js` /
`chunk-HH2WTORV.js`) return the same data as the static JSONs, plus an
AppSync WebSocket subscription for live updates.

## Anti-bot notes

Akamai fingerprints the TLS/HTTP-2 client. Python `httpx` and plain
`requests` get killed mid-stream; `curl_cffi` with `impersonate="chrome"`
walks through cleanly. A Colombian VPN is **not** required. Set
`Accept-Language` + `Accept-Encoding: gzip,deflate,br` (curl_cffi does
this automatically when `impersonate=` is set).
