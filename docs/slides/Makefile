.DEFAULT_GOAL := all
LATEXMK ?= latexmk
SOURCES := main.tex pipeline.tex

.PHONY: all check clean
all: check

main.pdf: $(SOURCES)
	$(LATEXMK) -pdf -file-line-error -interaction=nonstopmode -halt-on-error main.tex

check: main.pdf
	@test -s main.pdf
	@if grep -Ei 'undefined (references|citations)|(reference|citation).*undefined|multiply defined|Overfull' main.log; then \
		echo 'Unresolved references or overflowing slide content'; exit 1; \
	fi

clean:
	$(LATEXMK) -C main.tex
