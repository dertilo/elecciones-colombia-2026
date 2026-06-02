# E-14 OCR — empirical findings

What works and what doesn't when we point off-the-shelf OCR at the
merged 3-digit vote strips produced by `tools/extract_e14.py`.

## Why merge the three digit cells into one strip?

Text-line OCR models are trained on character sequences with
left-to-right context, not isolated single-character crops. For a
3-digit number it is cheaper *and* more accurate to give the OCR one
strip than three single-digit crops:

- 3× fewer inference calls.
- The model can use language-model-like priors over adjacent digits.
- A single output string is trivially shape-checked (`len == 3`,
  `all-numeric`).

This is why `e14_schema.py` emits one `vote_digits` cell per row
instead of three `vote_digit` cells. The strip is 900 px wide (the
three nominal 270-px digit boxes plus pad-x on each side).

## What did `microsoft/trocr-small-handwritten` actually return?

Tested on 200 strips (10 random PDFs × 20 strips on pages 1+2, post
merge). Steady-state ~336 ms/strip on CPU, batch 8.

| Cell content | Sample output | Frequency |
|---|---|---|
| 3 cleanly-written digits | `"0 4 4"`, `"0 7 8"`, `"0 3 6"` | works — including leading zeros |
| Empty (no ink) | `"a b c d e f g"` (exact, 28× / 200) | model's IAM fallback for uninformative input |
| Empty (no ink) | `"Jump to navigation"`, `"From the"`, `"I am"` | English hallucinations from the language prior |
| Sparse (1–2 real digits + dot/star markers) | `"# # 0"`, `"# 8"` | `#` as a placeholder; 95/200 outputs contain `#` |
| Messy handwriting | `"( 1 2F-F-"`, `"1 1/2-7"` | cursive-feature hallucinations |

Character histogram on 200 outputs: 486 spaces, 110 `0`, 95 `#`, 56
`a`, 55 `o`, 51 `"`, 39 `1`. The `#`-frequency rivalling `0`-frequency
is the clearest single signal that the model is mostly *not* reading
digits.

## What's the bottleneck?

**Not difficult handwriting** — cleanly-filled cells read correctly,
even with leading zeros. The bottleneck is **empty and dot/star-marker
cells**. TrOCR has no way to be told the Colombian convention "a dot
or star in an otherwise empty cell means zero" — its input is pixels,
not prompts.

Any practical pipeline needs to *pre-filter* "this cell has minimal
ink" and emit `"000"` for those cells directly, then invoke OCR only
on the remaining filled cells. The merge-then-OCR design above is
fine; the missing step is an ink-density check per sub-cell *before*
the merge step.

## How do we run TrOCR with this repo's `uv` setup?

The repo `pyproject.toml` pins Python ≥ 3.14. With Python 3.14 +
recent `transformers`, loading TrOCR-small-handwritten's tokenizer
fails because the slow→fast conversion path tries to read the
`sentencepiece.bpe.model` file via `tiktoken` and bails out.

Working invocation:

```
uv run --no-project --python 3.12 \
    --with "transformers==4.46.3" --with torch --with pillow \
    --with sentencepiece --with "protobuf<5" \
    python tools/ocr_inspect.py /tmp/e14-sample10 \
    --out /tmp/e14-ocr.html
```

`--no-project` bypasses the repo's Python pin; `--python 3.12` avoids
the tokenizer breakage; `transformers==4.46.3` predates the
problematic slow-loader path. Worth revisiting once upstream fixes
land.

## Next directions (not yet evaluated)

- `trocr-base-printed` — hand-printed digits may look more "printed"
  than "handwritten" to TrOCR; might lift accuracy on filled cells
  and give cleaner fallback on empty.
- Ink-density pre-filter → emit `"000"` for empty/marker cells, OCR
  only the rest.
- Custom small digit CNN trained on pseudo-labels seeded by the
  cells where TrOCR already returns clean 3-digit strings.
