# A-stage probe

Probe structure only. Do not expose or interpret extracted content. Store transient probe text in
a `mktemp -d` directory and remove it after the plan evidence has been reduced to counts.

## Procedure

Prefer the bundled deterministic probe, which implements the procedure below and emits only
content-free metrics:

```bash
python3 scripts/probe_pdf.py "$pdf"
```

1. Resolve the input to an absolute path and compute `sha256`, byte size, and filename.
2. Run `timeout 10s pdfinfo "$pdf"`. Parse `Pages` and `Encrypted`. Then run one
   `timeout 10s pdfinfo -box -f 1 -l "$pages" "$pdf"` command and retain each page's own width
   and height. Never reuse the first page's area for a mixed-size document.
3. If encrypted, stop probing and plan decryption. Explain that v1 does not distinguish owner and
   user passwords. Prefer `qpdf --password='<password>' --decrypt input.pdf decrypted.pdf` after
   confirmation; never request the password in a command that will be logged when a safer prompt
   is available.
4. Run exactly one full-document extraction process:

   ```bash
   timeout 10s pdftotext -enc UTF-8 -layout "$pdf" "$tmp/probe.txt"
   ```

5. Split `probe.txt` on `\f`. Poppler normally terminates each page with a form feed. Normalize
   the resulting list to the `pdfinfo` page count: remove at most one trailing empty segment; if
   counts still disagree, record `page-boundary-mismatch` and classify uncertain pages as scan.
6. Per page, retain only structural metrics: non-whitespace characters, letters/CJK characters,
   replacement/control characters, numeric-heavy line ratio, repeated horizontal gaps, aligned
   field starts, two-field row count, and the selected label. A field is a segment separated by
   two or more spaces; never treat ordinary word starts as table columns. Cluster starts within
   ±2 character columns so minor alignment drift does not hide two-column specification tables.
   Do not retain text snapshots.
7. Run `timeout 10s pdfimages -list "$pdf"`. Ignore `mask` and `smask` rows. Estimate each raster
   image's placed area from its pixel dimensions and X/Y PPI, divided by that page's area. Retain
   only per-page image count, aggregate area ratio, and count of images occupying at least 1% of
   the page. Do not extract or retain image content during the probe.
8. Run the global form precheck:

   ```bash
   timeout 10s bash -c 'strings "$1" | grep -c AcroForm' _ "$pdf"
   ```

   A positive count means `acroform-suspect`, not a confirmed form.

## Default classification rules

Evaluate in order and record the matched rule. Thresholds are defaults; any change must be shown
in the plan and justified under the rule-discipline table below.

| Rule | Default condition | Label |
|---|---|---|
| Empty text | non-whitespace characters `<= 20` | `scan` |
| Invalid mapping | characters `> 20` and `(letters + CJK) / printable < 0.35`, or replacement/control ratio `> 0.05` | `scan` |
| Table signals | at least 3 aligned field starts recur across at least 4 lines containing 3 or more fields; or at least 2 aligned starts recur across at least 6 lines containing 2 or more fields; or numeric-heavy lines `>= 35%` | `table-suspect` |
| Visual-layout signals | text exists and either aggregate non-mask raster area is `>= 5%`, or at least 2 non-mask images each occupy `>= 1%` of the page | `visual-layout` |
| Otherwise | no prior rule matched | `text` |

Treat `chars≈0` as the operational `<= 20` boundary. Count Unicode letters plus CJK Unified
Ideographs as effective word characters so Chinese PDFs are not penalized. Ignore whitespace and
form feed in denominators.

## Rule discipline: applicability, counterexample, impact

| Rule | Applicability | Counterexample | Impact |
|---|---|---|---|
| Empty text | Image-only or nearly blank pages | A deliberately sparse title page | Favors scan; may spend vision cost on sparse text |
| Invalid mapping | CID fonts without usable ToUnicode mappings or mojibake | Symbol-heavy equations, source code, or part-number lists | Favors scan to avoid corrupted text |
| Table signals | Key/value specification sheets, tables with 2+ aligned fields, or dense numeric rows | Two-column prose, equations, code listings, indexes | Marks suspect only; `find_tables()` plus visual validation must confirm and write false positives back |
| Visual-layout signals | Product sheets, diagrams, icon grids, and digital PDFs mixing text with meaningful graphics | Repeated logos, decorative bullets, or tiny footer images | Routes to vision-assisted structure recovery; text layer remains authoritative for values |
| AcroForm marker | PDFs whose object graph names AcroForm | Stale or flattened form objects | Global suspicion only; official `pdf` skill confirms |

## Probe evidence for testing

For oracle runs, cross-check the production image metrics against rendered page coverage and
review whether significant graphics are semantic or decorative. Retain only a pass/fail judgment
and structural reason, never page images or content snapshots.
