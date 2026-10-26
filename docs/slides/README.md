# Presentation slides

Build the 12-slide, 16:9 Beamer deck with standard TeX Live (pdfLaTeX, latexmk, Beamer, TikZ, Latin Modern and booktabs):

```bash
make -C docs/slides
```

The build checks for undefined references and overflowing content. `main.pdf` and auxiliary files are ignored; CI uploads the deck as `presentation-slides`. Body and table text use at least 14 pt. The pipeline adapts the report’s TikZ flow to show quote checking and the final advocate-only path explicitly.

All measured quantities come from `../report/numbers.md`. Preserve the distinction between headline and ablation runs, full-pipeline and final-config confidence gating, and clustered versus item-level intervals. The handwritten offset interval is item-level. The deck does not run experiments or expose private student data.

For a ten-minute talk, aim for roughly forty seconds per content slide, leaving the demo slide as the hand-off to the live app. Rehearse the sample-sheet → red-ink PDF → regrade sequence before Google Meet. The offline dry run can demonstrate initial marking; live regrading requires an available LLM service. No deployment or paid demonstration is performed by this build.

```bash
make -C docs/slides clean
```
