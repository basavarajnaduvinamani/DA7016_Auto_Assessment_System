# Final report

Build the report with TeX Live containing `latexmk`, pdfLaTeX, BibTeX, TikZ, `booktabs`, `adjustbox` and `natbib`:

```bash
make -C docs/report
```

This builds `main.pdf` and checks the final log for undefined references, citations and duplicate labels. Main text is ten pages, followed by references and the appendix. The PDF and auxiliary files are ignored; the existing CI workflow builds and uploads `final-report`.

`numbers.md`, maintained by Claude, is the source of truth for measured quantities. The five booktabs tables in `results/` are manually transcribed from that record and included via `\input{results/...}`. Tests compare their numeric cells with the source record and check numerical prose. Preserve the printed precision, separate headline runs from ablations, and retain the stated item-level versus question-clustered interval methods. Do not overwrite these curated tables with a generic results pack. Report building makes no model calls and runs no experiments.

The bibliography uses verified primary pages or records. Burrows et al.'s bibliographic metadata was also verified in Haller et al.'s survey (arXiv:2204.03503). The SPRAG citation is the Zenodo release, whose creator is recorded as “Sridevi B”, rather than an inferred dataset-paper citation. IndicOCR is cited as a model card without asserting an unknown publication year.

The appendix shows `results/figures/example_redink.png`, a page marked for the synthetic sample sheet S002. No real student answers, names or scans are committed. The aggregate handwritten results do not include private source material. OCR CER/WER, paired scan/transcript experiments and educational feedback studies were not measured and appear only as limitations/future work.

To remove build outputs without changing result assets:

```bash
make -C docs/report clean
```
