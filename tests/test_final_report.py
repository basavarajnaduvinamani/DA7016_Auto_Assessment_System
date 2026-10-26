"""The submitted report transcribes the architect-owned aggregate study record."""

import re
from pathlib import Path

import pytest

from conftest import ROOT

REPORT = ROOT / 'docs/report'
NUMBERS = (REPORT / 'numbers.md').read_text()


def numeric(text):
    return re.findall(r'(?<![A-Za-z])\d+(?:\.\d+)?', text)


def markdown_rows(section):
    text = NUMBERS.split(f'## {section}', 1)[1].split('\n## ', 1)[0]
    return [[cell.strip() for cell in line.strip('|').split('|')] for line in text.splitlines()
            if line.startswith('|') and not line.startswith('| ---')][1:]


@pytest.mark.parametrize('filename,section', [
    ('agreement', 'SPRAG test, main results'),
    ('ablation', 'Ablation ('),
    ('models', 'Model comparison on SPRAG dev'),
])
def test_table_rows_match_source_numbers_in_order(filename, section):
    source = markdown_rows(section)
    tex = (REPORT / 'results' / f'{filename}.tex').read_text()
    rows = [line for line in tex.splitlines() if '&' in line and line.rstrip().endswith(r'\\')]
    # Header rows contain no numeric measurements; model IDs may contain digits,
    # so only compare metric columns, preserving source precision and ordering.
    if filename == 'ablation':
        rows = rows[2:]
    else:
        rows = rows[1:]
    assert len(rows) == len(source)
    for actual, expected in zip(rows, source, strict=True):
        assert numeric('&'.join(actual.split('&')[1:])) == numeric(' '.join(expected[1:]))
        # Check the direction of every signed bias, not just its magnitude.
        actual_bias = actual.split('&')[-1].replace('$', '').strip().removesuffix(r'\\').strip()
        expected_bias = expected[-1]
        if expected_bias != '-':
            assert actual_bias == expected_bias


def test_handwritten_table_matches_source_and_keeps_offset_distinct():
    rows = markdown_rows('Handwritten classroom set')
    values = {label: value for label, value in rows}
    tex = (REPORT / 'results/handwritten.tex').read_text()
    assert numeric(values['QWK vs teacher']) == numeric('0.47 [0.32, 0.57]')
    assert '0.47 [0.32, 0.57]' in tex
    assert values['MAE'] == '0.55 of 2' and 'MAE (of 2) & 0.55' in tex
    assert values['Exact agreement / within 1 mark'] == '52% / 87%'
    assert r'52\% / 87\%' in tex
    assert values['Mean mark system vs teacher'] == '0.59 vs 1.07 (bias -0.49)'
    assert '0.59 / 1.07' in tex and '$-0.49$' in tex
    assert values['Leave-one-student-out offset correction'] == 'QWK 0.55 [0.44, 0.65] (item-level bootstrap), bias -0.03'
    assert '0.55 [0.44, 0.65]' in tex and '$-0.03$' in tex
    assert values['Flagged for teacher review'] == '75 of 135 questions' and '75 of 135' in tex


def test_injection_table_uses_recorded_counts_and_mark_change():
    source = NUMBERS.split('## Prompt-injection check', 1)[1].split('## Indic example', 1)[0]
    tex = (REPORT / 'results/injection.tex').read_text()
    for value in ['7 of 30', '0.17', '30 of 30', '0 of 570']:
        assert value in source and value in tex
    assert '3 reached full marks' in source and '3 answers' in tex


def test_report_has_no_unrecorded_numeric_literals_or_stale_placeholders():
    allowed = set(numeric(NUMBERS))
    texts = [REPORT / 'main.tex', *sorted((REPORT / 'sections').glob('*.tex')), *sorted((REPORT / 'results').glob('*.tex'))]
    for path in texts:
        text = path.read_text()
        # Preamble contains font sizes, margins and a course identifier, not results.
        if path.name == 'main.tex':
            text = text.split(r'\begin{abstract}', 1)[1].split(r'\end{abstract}', 1)[0]
        # Exclude diagram coordinates, layout dimensions and bibliography keys.
        text = re.sub(r'\b[a-z]+\d{4}[a-z_]*\b', '', text)
        text = text.replace('GPT-4', '')  # cited model name, not a study result
        text = re.sub(r'\\(?:cmidrule(?:\([^)]*\))?|multicolumn)\{[^}]*\}', '', text)
        text = re.sub(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', '', text, flags=re.S)
        text = re.sub(r'\d*\.?\d+\\(?:linewidth|textheight)', '', text)
        text = re.sub(r'\{[lrp0-9.\\]+\}', '', text)
        assert set(numeric(text)) <= allowed, (path, set(numeric(text)) - allowed)
        pending = re.findall(r'\\pending\{([^}]+)\}', text)
        assert pending == []
    results = (REPORT / 'sections/results.tex').read_text()
    assert all(f'\\resulttable{{{name}}}' in results for name in ('agreement', 'ablation', 'models', 'handwritten', 'injection'))
    assert not re.search(r'fig:(coverage|bias|ablation)|tab:(ocr|groups|robustness)', results)
    assert len((REPORT / 'sections/related_work.tex').read_text().split()) >= 550


def test_report_build_contract_retains_ci_reference_checks():
    makefile = (REPORT / 'Makefile').read_text()
    workflow = (ROOT / '.github/workflows/report.yml').read_text()
    assert 'undefined' in makefile and 'main.pdf' in makefile
    assert 'make -C docs/report check' in workflow and 'actions/upload-artifact' in workflow
    assert 'results/pending.tex' not in makefile
