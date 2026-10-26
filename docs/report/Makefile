.DEFAULT_GOAL := all
LATEXMK ?= latexmk
SOURCES := main.tex references.bib $(wildcard sections/*.tex results/*.tex results/figures/*.png)

.PHONY: all check clean
all: check

main.pdf: $(SOURCES)
	$(LATEXMK) -pdf -file-line-error -interaction=nonstopmode -halt-on-error main.tex

check: main.pdf
	@test -s main.pdf
	@if grep -Ei 'undefined (references|citations)|(reference|citation).*undefined|multiply defined' main.log; then \
		echo 'Unresolved or duplicate LaTeX references/citations'; exit 1; \
	fi

clean:
	$(LATEXMK) -C main.tex
