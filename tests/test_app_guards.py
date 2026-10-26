"""Demo guards and fallback behavior, with all provider traffic replaced by fakes."""

import importlib.util
import json
import socket
import zipfile
from pathlib import Path

import pymupdf
import pytest

from autoassess import demo
from autoassess.budget import BudgetExceeded
from autoassess.config import Settings
from autoassess.providers.base import LLMClient, OCRProvider
from autoassess.providers.scripted import ScriptedLLM
from autoassess.schemas import OCRPage
from autoassess.spec_builder import load_spec
from conftest import ROOT, SAMPLE

SPEC = load_spec(SAMPLE / "exam_spec.yaml")
SHEET = SAMPLE / "answer_sheets" / "S002.txt"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    for name in ("AUTOASSESS_DEMO_DRY_RUN", "AUTOASSESS_MAX_UPLOAD_MB", "AUTOASSESS_MAX_PAGES", "AUTOASSESS_DEMO_DAILY_SHEETS"):
        monkeypatch.delenv(name, raising=False)

    def blocked(*args, **kwargs):
        pytest.fail("Demo tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


class RecordingOCR(OCRProvider):
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def read_page(self, image_path, page_index, language_hint=None):
        self.calls.append(image_path)
        if self.error:
            raise self.error
        return OCRPage(page_index=page_index)


class FailingLLM(LLMClient):
    def __init__(self, error):
        self.error = error

    def complete_json(self, system, user, **kwargs):
        raise self.error


def settings(tmp_path, **kwargs):
    return Settings(cache_dir=tmp_path, llm_provider="openrouter", llm_api_key="test-key", **kwargs)


@pytest.mark.parametrize("key,expected", [("", "none"), ("test-key", "openrouter")])
def test_health_payload_no_provider_calls(tmp_path, monkeypatch, key, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("Health must not construct providers")

    monkeypatch.setattr(demo, "make_llm", forbidden)
    monkeypatch.setattr(demo, "make_ocr", forbidden)
    monkeypatch.setattr(demo, "make_translator", forbidden)
    config = Settings(cache_dir=tmp_path, llm_provider="openrouter", llm_api_key=key, ocr_provider="bodhan")
    assert demo.health_payload(config) == {"ok": True, "llm": expected, "ocr": "bodhan"}
    assert not (tmp_path / "demo_cap.json").exists()


@pytest.mark.parametrize("kind", ["oversize", "pages", "extension"])
@pytest.mark.parametrize("batch", [False, True])
def test_bad_uploads_rejected_before_ocr_or_llm(tmp_path, monkeypatch, kind, batch):
    ocr = RecordingOCR()
    factories = []

    def make_ocr(config):
        factories.append(config)
        return ocr

    monkeypatch.setattr(demo, "make_ocr", make_ocr)
    monkeypatch.setattr(demo, "make_llm", lambda *a, **k: pytest.fail("LLM must not be constructed"))
    if kind == "oversize":
        path = tmp_path / "large.txt"
        path.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        message = "10 MB"
    elif kind == "pages":
        path = tmp_path / "long.pdf"
        with pymupdf.open() as pdf:
            for _ in range(9):
                pdf.new_page()
            pdf.save(path)
        message = "8 page"
    else:
        path = tmp_path / "bad.exe"
        path.write_bytes(b"upload")
        message = "Use a .pdf"
    with pytest.raises(ValueError, match=message):
        if batch:
            demo.mark_class(SPEC, [SHEET, path], demo.Options(), settings(tmp_path))
        else:
            demo.mark_sheet(SPEC, path, demo.Options(), settings(tmp_path))
    assert factories == [] and ocr.calls == []
    assert not (tmp_path / "demo_cap.json").exists()


def test_configured_upload_limits_and_valid_pdf(tmp_path, monkeypatch):
    path = tmp_path / "sheet.PDF"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        pdf.save(path)
    monkeypatch.setenv("AUTOASSESS_MAX_PAGES", "1")
    with pytest.raises(ValueError, match="1 page"):
        demo.validate_upload(path)
    monkeypatch.setenv("AUTOASSESS_MAX_PAGES", "2")
    assert demo.validate_upload(path) == path
    monkeypatch.setenv("AUTOASSESS_MAX_UPLOAD_MB", "0.000001")
    with pytest.raises(ValueError, match="MB limit"):
        demo.validate_upload(path)


@pytest.mark.parametrize("error", [BudgetExceeded("private provider detail"), RuntimeError("429 token=private"), ConnectionError("private endpoint")])
def test_provider_error_returns_baseline_with_safe_note(tmp_path, monkeypatch, error):
    monkeypatch.setattr(demo, "make_llm", lambda *args, **kwargs: FailingLLM(error))
    result = demo.mark_sheet(SPEC, SHEET, demo.Options(), settings(tmp_path), tmp_path / "failed")
    baseline = demo.mark_sheet(SPEC, SHEET, demo.Options(use_llm=False, annotate=False), settings(tmp_path), tmp_path / "baseline")
    assert result.grade == baseline.grade
    assert result.pdf_path.is_file()
    note = " ".join(result.notes)
    assert "lexical baseline" in note and "private" not in note and "Traceback" not in note
    assert ("budget" in note) == isinstance(error, BudgetExceeded)


def test_provider_construction_error_falls_back(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        raise ValueError("private endpoint")

    monkeypatch.setattr(demo, "make_llm", failed)
    result = demo.mark_sheet(SPEC, SHEET, demo.Options(annotate=False), settings(tmp_path))
    assert result.grade.total > 0
    assert "unavailable" in " ".join(result.notes)
    assert "private" not in " ".join(result.notes)


def test_translation_error_falls_back_without_retry(tmp_path, monkeypatch):
    class FailedTranslator:
        def translate(self, *args, **kwargs):
            raise ConnectionError("private translation response")

    monkeypatch.setattr(demo, "make_llm", lambda *args, **kwargs: ScriptedLLM())
    monkeypatch.setattr(demo, "make_translator", lambda *args: FailedTranslator())
    result = demo.mark_sheet(SPEC, SHEET, demo.Options(language="Hindi", annotate=False), settings(tmp_path, bodhan_api_key="test-key"))
    baseline = demo.mark_sheet(SPEC, SHEET, demo.Options(use_llm=False, annotate=False), settings(tmp_path))
    assert result.grade == baseline.grade
    assert "Feedback is in English" in " ".join(result.notes)


def test_ocr_failure_does_not_fabricate_assessed_answers(tmp_path, monkeypatch):
    from PIL import Image

    path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "black").save(path)
    ocr = RecordingOCR(ConnectionError("private OCR response"))
    monkeypatch.setattr(demo, "make_ocr", lambda *args: ocr)
    monkeypatch.setattr(demo, "make_llm", lambda *a, **k: pytest.fail("Do not grade unreadable scans with an LLM"))
    result = demo.mark_sheet(SPEC, path, demo.Options(), settings(tmp_path, ocr_provider="bodhan"))
    assert ocr.calls and result.pdf_path.is_file()
    assert all(q.flags == ["unanswered"] for q in result.grade.questions)
    assert "no assessed answers" in " ".join(result.notes)
    assert "private" not in " ".join(result.notes)


def test_dry_run_produces_pdf_without_keys_or_paid_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")
    monkeypatch.setattr(demo, "make_translator", lambda *a: pytest.fail("Dry run must not translate"))
    config = settings(tmp_path, bodhan_api_key="test-key")
    result = demo.mark_sheet(SPEC, SHEET, demo.Options(language="Hindi"), config, tmp_path)
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) > 0
    assert result.html_path.is_file() and result.pages
    assert any("scripted" in note for note in result.notes)
    assert demo.health_payload(config) == {"ok": True, "llm": "fake", "ocr": "text"}
    assert not (tmp_path / "demo_cap.json").exists()


def test_daily_cap_remaining_and_batch_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DAILY_SHEETS", "2")
    monkeypatch.setattr(demo, "make_llm", lambda *args, **kwargs: ScriptedLLM())
    config = settings(tmp_path)
    cap = demo.daily_cap(config)
    assert cap.remaining() == 2
    demo.mark_sheet(SPEC, SHEET, demo.Options(annotate=False), config)
    assert cap.remaining() == 1
    _, archive, notes = demo.mark_class(SPEC, [SHEET, SAMPLE / "answer_sheets/S001.txt"], demo.Options(annotate=False), config)
    assert "limit" in " ".join(notes)
    assert cap.remaining() == 1  # the entire batch falls back without overshooting
    with zipfile.ZipFile(archive) as z:
        assert "S002.json" in z.namelist()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AUTOASSESS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOASSESS_LLM_PROVIDER", "openrouter")
    assert "remaining today: 1" in demo.status_markdown()


def test_class_reserves_each_llm_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOASSESS_DEMO_DAILY_SHEETS", "2")
    monkeypatch.setattr(demo, "make_llm", lambda *a, **kw: ScriptedLLM())
    demo.mark_class(SPEC, [SHEET, SAMPLE / "answer_sheets/S001.txt"], demo.Options(annotate=False), settings(tmp_path))
    assert demo.daily_cap(settings(tmp_path)).remaining() == 0


def test_class_provider_failure_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "make_llm", lambda *a, **kw: FailingLLM(BudgetExceeded("private")))
    _, archive, notes = demo.mark_class(SPEC, [SHEET], demo.Options(), settings(tmp_path))
    assert "budget" in " ".join(notes) and "private" not in " ".join(notes)
    with zipfile.ZipFile(archive) as z:
        grade = json.loads(z.read("S002.json"))
        assert grade["student_id"] == "S002" and "S002_marked.pdf" in z.namelist()


@pytest.fixture
def app_module(monkeypatch):
    pytest.importorskip("gradio")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    spec = importlib.util.spec_from_file_location("guarded_demo_app", ROOT / "src/autoassess/web/lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mounted_health_and_no_key_ui(app_module):
    from fastapi.testclient import TestClient

    assert TestClient(app_module.app).get("/healthz").json() == {"ok": True, "llm": "none", "ocr": "text"}
    assert app_module.grader_in.value == "Lexical baseline"
    assert not app_module.grader_in.interactive and not app_module.cgrader_in.interactive
    assert "disabled" in app_module.status.value


def test_sample_button_marks_s002_in_one_call(app_module):
    result = app_module.do_sample()
    assert Path(result[2]).is_file()
    assert "S002" in result[3] and "Total:" in result[1]
    assert len(result) == 7
    assert app_module.sample.value == "Try the sample sheet"


def test_bad_upload_becomes_gradio_error(app_module, tmp_path):
    path = tmp_path / "bad.exe"
    path.write_bytes(b"bad")
    with pytest.raises(app_module.gr.Error, match="Use a .pdf"):
        app_module.do_mark(None, str(path), "Lexical baseline", "OCR text", False, "English")


def test_regrade_error_keeps_original_mark(app_module, monkeypatch):
    from autoassess import providers

    last = app_module.do_sample()[-1]
    grade = last[1].grade.model_copy(deep=True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(providers, "make_llm", lambda *a: FailingLLM(ConnectionError("private")))
    message = app_module.do_regrade("Q1 / Q1.c1 (0)", "Please check", last)
    assert "unavailable" in message and "private" not in message
    assert last[1].grade == grade


def test_concurrent_daily_reservations_do_not_exceed_cap(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    cap = demo.DailyCap(tmp_path, 3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: demo.DailyCap(tmp_path, 3).take(), range(12)))
    assert sum(results) == 3
    assert cap.remaining() == 0


def test_keyless_custom_endpoint_counts_as_available(monkeypatch):
    import dataclasses

    from autoassess.config import Settings
    from autoassess.demo import llm_available

    base = Settings.load()
    assert llm_available(dataclasses.replace(base, llm_provider="custom", llm_base_url="http://localhost:11434/v1", llm_api_key=""))
    assert not llm_available(dataclasses.replace(base, llm_provider="openrouter", llm_api_key=""))


def test_regrade_state_is_per_visitor(app_module, monkeypatch):
    from types import SimpleNamespace
    from autoassess import regrade as regrade_module
    from autoassess import providers

    first = app_module.do_sample()[-1]
    second = app_module.do_mark(None, str(SAMPLE / 'answer_sheets/S001.txt'), 'Lexical baseline', 'OCR text', False, 'English')[-1]
    assert first[1].grade.student_id == 'S002'
    assert second[1].grade.student_id == 'S001'
    seen = []

    def fake_regrade(spec, grade, answer, *args, **kwargs):
        seen.append((grade.student_id, answer))
        return grade, SimpleNamespace(old_marks=0, new_marks=0, decision='keep', response='Reviewed', reason='')

    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setattr(providers, 'make_llm', lambda *a: object())
    monkeypatch.setattr(regrade_module, 'regrade', fake_regrade)
    for last in (first, second):
        assert 'Reviewed' in app_module.do_regrade('Q1 / Q1.c1 (0)', 'Check this', last)
    assert seen == [(last[1].grade.student_id, last[1].run.segments['Q1'].text) for last in (first, second)]
    assert isinstance(app_module.last_result, app_module.gr.State)
    assert not hasattr(app_module, 'STATE')
    deps = app_module.demo.config['dependencies']
    assert any(app_module.last_result._id in d['inputs'] for d in deps)
    assert sum(app_module.last_result._id in d['outputs'] for d in deps) == 2


@pytest.mark.parametrize('problem', ['no_sheet', 'no_choice', 'missing_segment', 'bad_choice', 'no_reason'])
def test_regrade_invalid_input_is_friendly(app_module, problem):
    last = app_module.do_sample()[-1] if problem != 'no_sheet' else None
    choice = None if problem == 'no_choice' else 'Q1 / Q1.c1 (0)'
    if problem == 'missing_segment':
        last[1].run.segments.pop('Q1')
    if problem == 'bad_choice':
        choice = 'invalid'
    reason = '' if problem == 'no_reason' else 'Please check'
    with pytest.raises(app_module.gr.Error, match='Mark a sheet|Choose a mark|unavailable|Say why'):
        app_module.do_regrade(choice, reason, last)


def test_scanned_example_is_available(app_module):
    config = app_module.demo.config
    datasets = [c for c in config['components'] if c['type'] == 'dataset']
    assert any('S002_scan.pdf' in str(c['props']['samples']) for c in datasets)


def test_advocate_is_default_and_critic_is_separate_in_ui(app_module, monkeypatch):
    for advocate, critic in ((app_module.advocate_in, app_module.critic_in), (app_module.cadvocate_in, app_module.ccritic_in)):
        assert advocate.value is True and advocate.label == 'Advocate review'
        assert critic.value is False and critic.label == 'Strict critic (lowers marks; off by default)'
    assert 'ablation' in app_module.ABOUT and 'optional' in app_module.ABOUT
    calls = []
    real_mark = app_module.mark_sheet

    def record(spec, sheet, opts):
        calls.append((opts.advocate_review, opts.strict_critic))
        opts.annotate = False
        return real_mark(spec, sheet, opts)

    monkeypatch.setattr(app_module, 'mark_sheet', record)
    app_module.do_sample()
    app_module.do_mark(None, str(SHEET), 'Lexical baseline', 'OCR text', False, 'English', True)
    assert calls == [(True, False), (False, True)]
    class_calls = []

    def record_class(spec, sheets, opts):
        class_calls.append((opts.advocate_review, opts.strict_critic))
        report = Path('class.html')
        report.write_text('Class')
        return report, Path('class.zip'), []

    monkeypatch.setattr(app_module, 'mark_class', record_class)
    app_module.do_class(None, [str(SHEET)], 'Lexical baseline', True)
    app_module.do_class(None, [str(SHEET)], 'Lexical baseline', False, True)
    assert class_calls == [(True, False), (False, True)]
