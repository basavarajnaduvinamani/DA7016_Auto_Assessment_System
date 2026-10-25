# Final report

Build the pending report with a standard TeX Live installation containing `latexmk`, pdfLaTeX, BibTeX, TikZ, `booktabs`, `adjustbox` and `natbib`:

```bash
make -C docs/report
```

This builds `main.pdf` and checks the final log for undefined references, citations and duplicate labels. The PDF and auxiliary files are ignored; CI uploads the PDF as `final-report`. The report uses only verified cited works. The bibliography starts from the archive inventory, which includes unused entries; the IndicOCR discussion has a citation TODO until a primary source is verified. No archived result numbers are used.

Generate a results pack as documented in `docs/evaluation.md`, then copy its assets and rebuild:

```bash
make -C docs/report results
make -C docs/report
```

The default input is `runs/results/` relative to the repository root. Override it with `RESULTS_DIR=/absolute/path/to/pack` if needed. Tables from `tables/*.tex` are flattened to `docs/report/results/*.tex`, matching the report's `\input{results/agreement}` convention. Figures retain their `figures/` directory. The target requires an agreement table and copies only the known tables and figures; absent optional outputs reset to generic pending assets so old results cannot silently remain. It does not run experiments or copy JSON, scans or answer sheets.

The appendix expects `results/figures/example_redink.png`. Supply an anonymised or synthetic page at `runs/results/figures/example_redink.png` before copying, or retain the pending image. The results command does not generate this example.

All committed result assets are visibly pending. The shared `results/pending.tex` and `results/figures/pending.png` are fallback templates, not measurements. Replacing the tables and figures does not replace prose marked with `\pending{...}`; retain those markers until the corresponding study supports an interpretation. Numerical results belong in the imported tables rather than hand-copied prose. Build settings, citations, course identifiers and automatic section/page numbering are document metadata, not empirical results.

To remove build outputs without changing result assets:

```bash
make -C docs/report clean
```
