#!/usr/bin/env bash
# Download the MOE (Misión de Observación Electoral) mesa-level
# corpus for the 2022 Colombian presidential election.
#
# MOE republished the per-mesa results that the Registraduría supplied
# to them, in xlsx form. Schema is one row per mesa with DIVIPOLA
# (departamento, municipio, zona, num_puesto, puesto, num_mesa) and one
# column per candidate plus blank / unmarked / null vote counts. About
# 103,365 rows for first round.
#
# Status (last verified 2026-06-02):
#   1ra vuelta primer avance (preconteo): live
#   1ra vuelta CNE definitivo:           live
#   2da vuelta preconteo 99.99%:         HTTP 410 (Google Sheet deleted)
#   2da vuelta CNE definitivo:           HTTP 410 (Google Sheet deleted)
#
# See docs/historical-elections-data-sources.md for context and for
# workarounds for the 2nd-round data.

set -euo pipefail

OUT_DIR="${1:-data_2026/historical/2022_mesa_moe}"
mkdir -p "$OUT_DIR"

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0'

fetch() {
    local url="$1" out="$2"
    echo "  -> $out"
    curl -sSL --max-time 120 -A "$UA" "$url" -o "$OUT_DIR/$out" \
        -w "     HTTP %{http_code}  %{size_download} bytes\n"
}

echo "MOE 2022 presidential mesa-level corpus -> $OUT_DIR"
echo

echo "1ra vuelta (29 May 2022)"
fetch "https://www.moe.org.co/wp-content/uploads/2022/06/Escrutinios-primera-vuelta-presidencial-mesa-a-mesa-1.xlsx" \
      "1ra_vuelta_preconteo_primer_avance.xlsx"
fetch "https://www.moe.org.co/wp-content/uploads/2022/06/Escrutinio-definitivo-1ra-vuelta-presidencial-2022.xlsx" \
      "1ra_vuelta_cne_definitivo.xlsx"

echo
echo "2da vuelta (19 June 2022): both Google Sheets links 410 Gone."
echo "  Preconteo 99.99%:   https://docs.google.com/spreadsheets/d/1LUladRfeuL8euCerXeYfR717hXi7-K6f/"
echo "  CNE definitivo:     https://docs.google.com/spreadsheets/d/1nG4yMvA4MSDIarZHYlokj_ZgioJ97SCg/"
echo "  See docs/historical-elections-data-sources.md for recovery options."
