.DEFAULT_GOAL := all
LATEXMK ?= latexmk
RESULTS_DIR ?= ../../runs/results
TABLES := agreement ablation robustness ocr groups
FIGURES := coverage bias ablation example_redink
SOURCES := main.tex references.bib $(wildcard sections/*.tex results/*.tex results/figures/*.png)

.PHONY: all check results clean
all: check

main.pdf: $(SOURCES)
	$(LATEXMK) -pdf -file-line-error -interaction=nonstopmode -halt-on-error main.tex

check: main.pdf
	@test -s main.pdf
	@if grep -Ei 'undefined (references|citations)|(reference|citation).*undefined|multiply defined' main.log; then \
		echo 'Unresolved or duplicate LaTeX references/citations'; exit 1; \
	fi

# Copy only report assets, never student sheets or run JSON. Optional outputs
# absent from the pack are reset to the committed generic pending assets.
results:
	@test -f "$(RESULTS_DIR)/tables/agreement.tex" || \
		{ echo 'Missing results pack: run autoassess results first or set RESULTS_DIR'; exit 1; }
	@set -e; for name in $(TABLES); do \
		if test -f "$(RESULTS_DIR)/tables/$$name.tex"; then \
			cp "$(RESULTS_DIR)/tables/$$name.tex" "results/$$name.tex"; \
		else cp results/pending.tex "results/$$name.tex"; fi; \
	done
	@set -e; for name in $(FIGURES); do \
		if test -f "$(RESULTS_DIR)/figures/$$name.png"; then \
			cp "$(RESULTS_DIR)/figures/$$name.png" "results/figures/$$name.png"; \
		else cp results/figures/pending.png "results/figures/$$name.png"; fi; \
	done
	@echo 'Copied report assets; omitted sections use pending placeholders.'

clean:
	$(LATEXMK) -C main.tex
