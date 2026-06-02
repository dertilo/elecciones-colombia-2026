# What `delegados` and `transmisión` actually mean

Domain context. The portal architecture (which host serves what, how
to fetch) is in `registraduria-e14-architecture.md`; this note exists
to explain why we want **both** corpora rather than picking one.

## Why does a single mesa produce multiple E-14s?

Because two independent counting chains run on the same handwritten
tally. The jurados de votación (citizens drafted to staff each mesa)
fill out several carbon copies of the same E-14 form after closing the
polls. The copies are then distributed to chains that operate in
parallel:

| Copy | Recipient | Where it ends up |
|---|---|---|
| E-14 Transmisión | Puesto's transmission operator (Registraduría staff) | Photographed/scanned same night, uploaded to the *preconteo* |
| E-14 Delegados | Municipal delegados of the Registraduría | Travels with sealed materials to the Comisión Escrutadora |
| E-14 Claveros | Sealed inside the urna | Opened only if a reconteo is ordered; not published online |

The first two are what the public Registraduría portal exposes —
respectively at `divulgacione14presidentet....` (transmisión) and
`divulgacione14presidente....` (delegados).

## What is the difference in legal status?

- **Transmisión** is the fast, on-night preliminary count
  (*preconteo*). It drives election-night TV results, the
  Registraduría's real-time dashboard, and early reactions from the
  press. It is **not legally binding**. The transmission chain has a
  non-trivial transcription-error rate — numbers are read off scans
  under time pressure.
- **Delegados** is the basis of the **official escrutinio** carried
  out by the Comisiones Escrutadoras in the days after the election,
  in the presence of party witnesses (*testigos electorales*) and the
  Ministerio Público. It is the **document of legal record**;
  objections, recounts, and impugnment proceed against the numbers on
  this copy. Published to the portal a day or two later than
  transmisión.

## Why scrape both?

The standard fraud-verification methodology (used by El Colombiano,
MOE, and Colombian electoral-fraud academic work) is precisely the
per-mesa comparison of the two:

> For each mesa, compare candidate-by-candidate tallies on the
> transmisión PDF and the delegados PDF. They should agree up to OCR
> and data-entry noise. Systematic discrepancies — especially when
> directional (always favouring one candidate) and clustered (specific
> puestos or municipios) — are the canonical fraud signal.

Neither corpus replaces the other. Transmisión is the snapshot on
which manipulation has the largest *narrative* impact; delegados is
the truth against which transmisión is audited.
