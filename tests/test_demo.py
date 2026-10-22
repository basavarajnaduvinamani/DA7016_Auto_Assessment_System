"""The web demo's logic, run without Gradio and without any key."""

from autoassess.config import Settings
from autoassess.demo import DailyCap, Options, mark_class, mark_sheet
from autoassess.spec_builder import load_spec
from conftest import SAMPLE

SPEC = load_spec(SAMPLE / "exam_spec.yaml")


def test_mark_sheet_without_a_key_falls_back_to_the_baseline(tmp_path):
    r = mark_sheet(SPEC, SAMPLE / "answer_sheets" / "S002.txt", Options(), Settings(cache_dir=tmp_path), tmp_path)
    assert r.pdf_path.exists() and r.pages and r.html_path.exists()
    assert any("lexical baseline" in n for n in r.notes)
    assert r.summary_md.index("Marks:") > r.summary_md.index("**Q1**") and "AI-marked" in r.summary_md


def test_scan_without_ocr_is_a_clear_error(tmp_path):
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG")
    try:
        mark_sheet(SPEC, img, Options(use_llm=False), Settings(cache_dir=tmp_path, ocr_provider="text"), tmp_path)
    except ValueError as err:
        assert "no OCR is configured" in str(err)
    else:
        raise AssertionError("expected a ValueError")


def test_daily_cap(tmp_path):
    cap = DailyCap(tmp_path, 2)
    assert cap.take() and cap.take() and not cap.take()


def test_mark_class_writes_report_and_zip(tmp_path):
    sheets = [SAMPLE / "answer_sheets" / f"S00{i}.txt" for i in (1, 2, 3)]
    rpath, zpath, notes = mark_class(SPEC, sheets, Options(use_llm=False), Settings(cache_dir=tmp_path))
    import zipfile

    names = zipfile.ZipFile(zpath).namelist()
    assert "class_report.html" in names and "S001_marked.pdf" in names and "S003.json" in names
    assert "Most missed rubric points" in rpath.read_text()
