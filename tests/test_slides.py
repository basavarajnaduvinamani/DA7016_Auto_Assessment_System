"""Keep the talk aligned with the reviewed study and legible slide sources."""

import re

import yaml

from conftest import ROOT

SLIDES = ROOT / 'docs/slides'
SOURCE = (SLIDES / 'main.tex').read_text()
NUMBERS = (ROOT / 'docs/report/numbers.md').read_text()
FRAMES = re.findall(r'\\begin\{frame\}(.*?)\\end\{frame\}', SOURCE, re.S)


def numeric(text):
    return re.findall(r'(?<![A-Za-z0-9])\d+(?:\.\d+)?', text)


def source_rows(section):
    section_text = NUMBERS.split(f'## {section}', 1)[1].split('\n## ', 1)[0]
    return [[cell.strip() for cell in line.strip('|').split('|')] for line in section_text.splitlines()
            if line.startswith('|') and not line.startswith('| ---')][1:]


def test_twelve_slides_share_report_identity_and_cover_demo():
    assert len(FRAMES) == 12
    report = (ROOT / 'docs/report/main.tex').read_text()
    assert re.search(r'\\title\{([^}]+)\}', SOURCE).group(1) == re.search(r'\\title\{([^}]+)\}', report).group(1)
    assert 'Basavaraj A Naduvinamani (DA25C005)' in SOURCE
    assert 'DA7016, IIT Madras' in SOURCE
    assert 'no teacher action on each answer' in FRAMES[1]
    assert 'defer to a teacher' in FRAMES[1]
    assert all(word in FRAMES[-1] for word in ('Sample sheets', 'Review queue', 'regrade request', 'red-ink PDF', 'LLM service'))


def test_headline_and_ablation_cells_preserve_source_precision_and_bias():
    main = source_rows('SPRAG test, main results')
    # Human / baseline / final are rows 0 / 1 / 4 of the study record.
    expected_main = [main[i][1:4] for i in (1, 4, 0)]
    headline = [line for line in FRAMES[5].splitlines() if '&' in line][1:]
    assert len(headline) == len(expected_main)
    for line, expected in zip(headline, expected_main, strict=True):
        # The interval appears in the block below the table, rather than its cell.
        expected[0] = expected[0].split(' [')[0]
        assert numeric('&'.join(line.split('&')[1:])) == numeric(' '.join(expected))
    assert '0.723 [0.667, 0.773]' in FRAMES[5]
    assert 'clustered by question' in FRAMES[5]

    ablation = source_rows('Ablation (')
    rows = [line for line in FRAMES[6].splitlines() if '&' in line][1:]
    assert len(rows) == 4
    for line, expected in zip(rows, ablation[:4], strict=True):
        assert numeric('&'.join(line.split('&')[1:])) == numeric(' '.join(expected[1:4]))
        assert line.split('&')[-1].replace('$', '').strip().removesuffix(r'\\').strip() == expected[3]
    assert 'separate from the headline run' in FRAMES[6]


def test_numeric_claims_come_from_the_aggregate_record():
    # Preamble sizes, course identity and Beamer geometry are document metadata.
    content = SOURCE.split(r'\begin{document}', 1)[1]
    assert set(numeric(content)) <= set(numeric(NUMBERS))
    assert '62\\% auto-marked at MAE 0.66' in FRAMES[7]
    assert '92\\% coverage at MAE 0.76' in FRAMES[7]
    assert 'Full pipeline: advocate + critic' in FRAMES[7]
    assert 'Final configuration: advocate only' in FRAMES[7]
    assert '0.47 [0.32, 0.57]' in FRAMES[8] and 'question-clustered' in FRAMES[8]
    assert '0.55 [0.44, 0.65]' in FRAMES[8] and 'item-level' in FRAMES[8]
    assert 'not the new advocate-only default' in FRAMES[8]
    assert all(value in FRAMES[9] for value in ('7 of 30', '+0.17', '30 of 30', '0 of 570', '5/5'))
    assert 'Paraphrases may evade' in FRAMES[9] and 'not an evaluation' in FRAMES[9]


def test_slide_fonts_do_not_shrink_body_or_tables():
    assert r'\documentclass[14pt,aspectratio=169]{beamer}' in SOURCE
    pipeline = (SLIDES / 'pipeline.tex').read_text()
    for text in (SOURCE, pipeline):
        assert not re.search(r'\\(?:tiny|scriptsize|footnotesize|small|scalebox|resizebox)\b|\[shrink', text)
        assert all(float(size) >= 14 for size in re.findall(r'\\fontsize\{([\d.]+)\}', text))
    assert 'font=\\normalsize' in pipeline
    nodes = re.findall(r'\\node\[stage[^\]]*\]\s*\(([^)]+)\)', pipeline)
    assert nodes == ['ingest', 'ocr', 'segment', 'grade', 'quote', 'advocate', 'confidence', 'feedback', 'ink']
    for a, b in zip(nodes, nodes[1:]):
        assert f'({a})--({b})' in pipeline
    assert r'\times 3' in pipeline


def test_ci_builds_and_uploads_deck_and_preserves_report():
    # BaseLoader preserves GitHub Actions' "on" key as a string.
    workflow = yaml.load((ROOT / '.github/workflows/report.yml').read_text(), Loader=yaml.BaseLoader)
    for event in ('push', 'pull_request'):
        assert 'docs/slides/**' in workflow['on'][event]['paths']
    for job, directory, artifact in [('report', 'docs/report', 'final-report'), ('slides', 'docs/slides', 'presentation-slides')]:
        steps = workflow['jobs'][job]['steps']
        assert any(s.get('with', {}).get('working_directory') == directory for s in steps)
        assert any(s.get('run') == f'make -C {directory} check' for s in steps)
        assert any(s.get('with', {}).get('name') == artifact and s['with']['path'] == f'{directory}/main.pdf' for s in steps)
    makefile = (SLIDES / 'Makefile').read_text()
    assert 'pipeline.tex' in makefile and '-halt-on-error' in makefile
    assert 'Overfull' in makefile and 'undefined' in makefile
    assert 'main.pdf' in (SLIDES / '.gitignore').read_text()
