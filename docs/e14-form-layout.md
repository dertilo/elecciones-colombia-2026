# E-14 form layout (2026 presidential)

Visual structure of the PDF *actas* themselves. The portal architecture
(how to fetch them) lives in `registraduria-e14-architecture.md`. This
note exists to drive geometric segmentation of the 121 844 PDFs without
re-deriving the layout from scratch.

## How many distinct templates are there?

Two, both 3 pages, both with a 7+6 candidate split. Detect by title block
or by page size — they don't overlap.

| Template | Title block | Header fields | Page size (pts) |
|---|---|---|---|
| Regular | `DELEGADOS` or `TRANSMISIÓN` | `DEPARTAMENTO / MUNICIPIO / ZONA / PUESTO / MESA / LUGAR` | ~870 × 2610 |
| Consulado (`dep=88`) | `CÓNSUL / EMBAJADOR` | `CONSULADO / PAÍS / ZONA / PUESTO / MESA / LUGAR` | ~870 × 2630 |

Page-size variation within "regular" is 862-938 × 2588-2631 pts across
departamentos — scanner-export noise, **not** a template variant. The
aspect ratio (~1:3) is stable. A homography per page handles the drift.

The two templates are roughly the same physical page size; "consulado
is smaller" was an early misreading from a single dep=88 PDF whose
page-size field happened to be unusual. The reference
`data_2026/e14/delegados/88/815/005/02/064_*.pdf` rasterises to
3600 × 10892 at 300 DPI — same scale as a regular page (3600 × 10825).

## What is on each page?

Same for both templates. Every page starts with the same header block
(barcode + QR + ACTA title + DEPARTAMENTO/MUNICIPIO/ZONA/PUESTO/MESA/LUGAR
lines + the `X N-NN-NN-NN X` mesa-code line) and ends with the same
footer (see "What is in the footer?" below). The middle differs:

- **Page 1** — `NIVELACIÓN DE LA MESA` solid-black bar, then its 3
  totals rows (`TOTAL VOTANTES FORMULARIO E-11`, `TOTAL VOTOS EN LA
  URNA`, `TOTAL VOTOS INCINERADOS`), then the `CANDIDATO | AGRUPACIÓN
  | VOTACIÓN` solid-black bar, then **7** candidate rows (numbered
  1-7). Each candidate row is a rounded rectangle with photo + party
  logo + 3 vote-digit positions, with the candidate's printed name
  below the rectangle.
- **Page 2** — `CANDIDATO | AGRUPACIÓN | VOTACIÓN` bar (no NIVELACIÓN
  on this page), then **6** candidate rows (numbered 8-13), then 4
  bottom summary rows (`VOTOS EN BLANCO`, `VOTOS NULOS`, `VOTOS NO
  MARCADOS`, `SUMA TOTAL CANDIDATOS + EN BLANCO + NULOS + NO
  MARCADOS`).
- **Page 3** — `CONSTANCIAS DE LOS JURADOS DE VOTACIÓN` solid-black
  bar, big empty constancias text block, `¿HUBO RECUENTO DE VOTOS?
  SÍ/NO` line with checkbox marks, `SOLICITADO POR:` + `EN
  REPRESENTACIÓN DE:` text fields, then **6** signature blocks in a
  2×3 grid (each `FIRMA JURADO N` + handwritten signature + `C.C.`
  + cedula number).

The 7+6 candidate split and the 6 signature blocks are verified by
inspection of `data_2026/templates/ref/regular-{1,2,3}.png` at 300 DPI;
consulado references appear identical in structure.

### Numeric fields look like 3 discrete digit positions

Vote counts (`0 3 2`, `1 7 9`) and totals are written into **3 evenly
spaced digit positions** within each numeric cell, not as a single
free-flowing number. **The positions are spatial guides, not printed
sub-boxes**: a column-ink projection across a candidate-row strip at
300 DPI shows only the rounded rectangle's outer left/right borders
(strong vertical lines at the row's x-extent boundaries) and *no*
internal vertical lines at the digit-position x's. Each digit cell
must therefore be cropped from a hand-tuned x-position, not snapped
to a printed edge.

Measured digit geometry (for the schema in `tools/e14_schema.py`):
3 cells per votación field at x = {2500, 2800, 3100}, each 270 px
wide × ~55% of row height tall, vertically centered in the row.

(History note: this doc earlier left this question open pending a
600-DPI inspection. The 300-DPI column projection resolves it —
600 DPI would only confirm.)

## Which anchors can drive a homography?

Every page carries:

0. **Four solid-black registration squares**, one per page corner
   (~100×100 px at the reference rasterization, full-page extent).
   These are printed by the Registraduría specifically as fiducial
   marks. They are the strongest available basis for a 4-point
   perspective homography: maximally spread, geometrically trivial
   (so robust to blur and contrast loss), and survive distortion that
   breaks barcode decoding or bar-darkness detection. Detector lives
   at `tools/detect_anchors.py:detect_corner_squares` — scoring picks
   the dark blob **closest to the page corner**, not the largest, so
   QR finder patterns and page-number ink don't win.
1. **Code-128 barcode**, top-centre. Decode with `pyzbar`; its corners
   give a tight quadrilateral. **The payload is NOT the mesa code** —
   it's a 44-char base64 string (32 bytes), different on every page of
   the same acta, presumably a per-page signature/hash. Use the polygon
   geometrically; don't try to cross-check it against the filename.
2. **QR code**, top-left, beside the title block. A second top-edge
   anchor, easier to localise than the Code-128 (square footprint, no
   ambiguity in orientation). Use both barcodes together for extra
   redundancy near the page top.
3. **`X N-NN-NN-NN X` mesa-code line** — two large cross marks flanking
   a dash-separated code. Strong horizontal anchor with built-in scale.
4. **Solid-black banner bars** (pages 1-2). **Page 1 has TWO** banner
   bars stacked vertically: `NIVELACIÓN DE LA MESA` above
   `CANDIDATO | AGRUPACIÓN | VOTACIÓN`, both equally dark and equally
   full-width. A "biggest darkest horizontal band" detector picks the
   earliest one, i.e. NIVELACIÓN, not CANDIDATO. To use the CANDIDATO
   bar specifically, either find both bars and take the lower, or
   OCR-classify by text. Page 2 has only the CANDIDATO bar; page 3 has
   the `CONSTANCIAS DE LOS JURADOS DE VOTACIÓN` bar in its place.
5. **`KIT NNNNN` footer** — printed near the bottom margin on every page.
6. **`Ver: 01  Pag: X de 3`** — top-right corner, printed in fixed
   position. Doubles as a page-number sanity check (we got all three
   pages) and a template-version field (if the form is ever re-versioned,
   `Ver:` changes).

Three anchor points suffice for a 2D affine fit; four+ gives
overdetermined least-squares.

### What survives in real-world scans?

Empirically, on the dep=88 (consulates) subset:

- **Clean digital PDFs** (the form rendered server-side, never
  printed) keep every anchor at reference position. All 4 corner
  squares + barcode + header bar detect cleanly.
- **Phone photos of the printed form** often crop the top of the form
  too tightly — the photographer frames against the candidate rows
  and the **top two corner squares end up outside the frame**. The
  bottom squares survive because there's whitespace below candidate 7.
  Fallback: combine the two surviving corner squares with the header
  bar and/or barcode for a 4-point fit.
- **`PÁGINA NO DIGITALIZADA` placeholder pages** exist in the corpus.
  When a page wasn't actually scanned, the Registraduría serves a
  stub PDF with only the Registraduría coat-of-arms and the literal
  text "PÁGINA NO DIGITALIZADA". Anchor detection correctly returns
  zero anchors on these — a useful "this scan is unusable" signal,
  not a detector bug.

## What is in the footer?

Three fields, all in the same bottom strip on every page:

- `No. Form NNNNN` — form number (per-acta, same on all 3 pages).
- `KIT N,NNN` — kit number (per-acta, same on all 3 pages).
- `Csv NNNNNN` — template-version code, **sequential per page** within
  one acta (page 1 = N, page 2 = N+1, page 3 = N+2). Useful as a
  template-version anchor: if the form is re-issued, the Csv numbering
  scheme changes. Sequential numbering per page also gives a sanity
  check that the 3 pages of one acta belong together.

(An earlier version of this doc mentioned a `Cra NNNNN` code in the
footer — that label doesn't appear on the 25/001/006/06/009 reference;
the field is `Csv` on these references.)

### Why anchor-based homography, not grid detection?

The form is **not a ruled grid**. Concretely:

- Each candidate row is a **rounded rectangle**, not a sharp box. Long
  horizontal/vertical morphological opening recovers the straight
  edges fine but drops the rounded corners, leaving four corner gaps
  per row. Cell-as-connected-component then leaks through the gaps
  into the page exterior and the whole row gets filtered out as
  "outside".
- There are **no internal column dividers** between
  `CANDIDATO | AGRUPACIÓN | VOTACIÓN` inside the candidate rows. The
  three column labels appear in the black header bar; below it, each
  candidate row is one open area with the columns implied by
  horizontal position.
- Several fields (totals, votación numbers) sit inside open rectangles
  with no internal subdivisions.

The cell geometry is **positional** (defined by the visual designer
relative to the anchors), not derivable from ink on the page.
Segmentation must therefore be: detect anchors → homography to
template space → read cells from hardcoded reference-space
rectangles. There is no shortcut where the form "tells us" where its
cells are.

An earlier `tools/detect_grid.py` explored pure line-detection on a
300-DPI reference; the line mask it produced made the dropped-corner
failure mode visually obvious, but its connected-components cell
extraction was a dead end for this form. Tool removed during the
squash that introduced the anchor/projection pipeline.

### Bottom-up cell discovery doesn't work either

The "discover cell positions from the reference PNG, then label them"
shortcut also doesn't fly. Different cell types need different
primitives, and no single primitive covers them all:

- **Small isolated boxes** (mesa-info digit slots, X-mesa-code-line
  positions) — found cleanly as **inner contours** of the ink mass
  (`RETR_CCOMP`, take holes whose parent ink-blob is large enough to
  not be a letter glyph). Letter-shaped holes inside printed text
  ("o", "0") are the main false positive; filter by parent-bbox area
  (>~200 k px² at 300 DPI).
- **Large content-bearing rounded rectangles** (candidate rows,
  NIVELACIÓN totals, signature blocks) — inner-contour FAILS because
  the photo/logo/text inside the rectangle fragments the interior into
  many sub-holes; the rectangle-as-a-whole hole doesn't exist. Outer
  contour FAILS too because adjacent rectangles are joined into one
  giant ink blob by even small morphological closes (the column-header
  bar above row 1 sits within ~30 px of the row's top edge, and once
  bridged the whole zone becomes one outer contour).
- Horizontal **row-projection** (sum ink per scanline → peaks) is more
  promising for the rounded-rectangle zones, but each rectangle
  produces 2-3 separate peaks (top edge line ~0.9 ink, interior
  content ~0.2-0.7, bottom edge line ~0.9), and the printed name
  below each candidate adds yet another peak. Run-length detection
  with a wrong `gap_bridge` either splits one rectangle into 3-4
  pieces (gap too small) or fuses 3-4 adjacent rectangles into one
  super-row (gap too big — the inter-rectangle whitespace is ~50-80
  px, similar to the within-rectangle interior gaps).
- The compounding gotcha: if the binarized mask already had a
  morphological close applied (say 15 px), and `_find_rows` then
  bridges its own gap (say 30 px), the total gap-fill width is the
  sum (~60 px), not the larger of the two. Skip morph-close on the
  input to row-projection.

The takeaway: bottom-up detection on a fixed-layout form fights the
form's structure. Encode the layout once as a **schema** (a JSON or
Python data structure listing per-page zones + row counts + row pitch
+ within-row column offsets), then project anchor-relative. Bottom-up
detection on the reference is at most a sanity-check, not a
substitute for the schema.

### There is no vector reference in the corpus

Scanned a 200-PDF non-88 random sample plus 10 dep=88 samples with
`pdffonts` + `pdftotext`: **zero have embedded fonts or extractable
text**. The whole corpus appears to be image-only PDFs. So the
"extract printed cell rectangles from a vector PDF's drawing operators"
shortcut doesn't apply — there's no vector source on disk to extract
from. The schema must come from manual measurement on the 300-DPI
rasterised reference, or from an external vector blank that
Registraduría publishes (if any — not searched).

### Anchor search must be whole-page, not margin-anchored

For ~98% of the corpus the form fills the canvas with millimetre
margins and anchors live exactly where the layout says. But the
`dep=88` consulado subset contains ~2 500 PDFs (~2% of the corpus)
that are **smartphone photos** of the printed acta, often shot at an
angle on a desk. The form floats freely on the canvas, rotated and
sometimes only filling a third of the page. Search the whole image
for each anchor — all four are distinctive enough that whole-page
search doesn't false-match.

Concentrated in dep=88 munis 815, 685, 455, 675, 360, … — apparently
specific consulates that photographed rather than scanned. See
`scrape-2026-findings.md` for the size-bucket breakdown.

## How is the form-type detected?

Cheapest test first: page width. <500 pts → consulado, else regular. As
a safety net, OCR the title-block strip (small ROI, ~50 px tall) and
look for the literal `DELEGADOS` vs `CÓNSUL` / `EMBAJADOR`.

## What about the title block — `DELEGADOS` vs `TRANSMISIÓN`?

The two regular templates are byte-for-byte the same form. The title
block is what tells them apart: the no-`t` host serves PDFs that say
`DELEGADOS`, the `…presidentet` host serves PDFs that say `TRANSMISIÓN`.
See `registraduria-e14-architecture.md` for the host-to-corpus mapping.

Segmentation can be agnostic to the distinction — both corpora share
the same cell geometry and anchors.

## How to pick a reference PDF for template-baking?

Filter by **PDF page size**, not file size. `find … -printf '%s'` and
sorting ascending picks the wrong thing:

- The smallest non-88 PDFs (~10-13 KB) are **image-only PDFs rendered
  at 1/4 the standard page size** (`pdfinfo` shows `217 × 643 pts`,
  not `~870 × 2610`). They rasterize to ~900-px-wide canvases at
  300 DPI, well below the resolution needed for template work.
- The smallest dep=88 PDFs (~80 KB) happen to be properly-scaled
  scans; size-sort works there by coincidence.

What I used as a regular reference once I noticed:
`data_2026/e14/delegados/25/001/006/06/009_*.pdf` — 100 KB, page size
`864 × 2598 pts`, rasterizes to 3600 × 10825 at 300 DPI. Pick by
running `pdfinfo` and selecting a PDF whose page size matches the
expected `~870 × 2610 pts`.

## Department codes are Registraduría's own, not DIVIPOLA

The 2-digit prefix in mesa codes / file paths is **not** the DIVIPOLA
code. Registraduría uses a separate electoral coding (34 codes
including `01`, `03`, `07`, `09`, `88`-consulado, … none of which exist
in DIVIPOLA). One concrete confirmation from the eyeballed sample:
`dep=05, mun=097` decodes to `BOLIVAR / SIMITÍ` in the acta header,
whereas DIVIPOLA `05` is Antioquia.

Within `dep=88` (Consulados), the second level is the consulate
country/city rather than a Colombian municipality — e.g.
`88/360 = Estados Unidos`.

For aggregation/reporting we'll need to build a Registraduría-code →
DIVIPOLA-code lookup. The acta headers themselves carry the human
names (`DEPARTAMENTO: NN - NAME`, `MUNICIPIO: NNN - NAME`) so the
mapping can be harvested from a few clean actas per dep.
