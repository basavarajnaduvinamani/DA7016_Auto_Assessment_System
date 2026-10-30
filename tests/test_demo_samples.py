"""Bundled demo resources also work outside an editable checkout."""

import fnmatch
import runpy
import shutil
import tomllib
from pathlib import Path

import pymupdf
from conftest import ROOT, SAMPLE

from autoassess import demo
from autoassess.spec_builder import load_spec


def test_packaged_samples_match_source_and_are_included():
    bundled = Path(demo.__file__).parent / "sample_exam"
    source_files = {p.relative_to(SAMPLE) for p in SAMPLE.rglob("*") if p.is_file()}
    bundled_files = {p.relative_to(bundled) for p in bundled.rglob("*") if p.is_file()}
    assert source_files == bundled_files
    patterns = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["autoassess"]
    for relative in source_files:
        assert (SAMPLE / relative).read_bytes() == (bundled / relative).read_bytes()
        assert any(fnmatch.fnmatch(f"sample_exam/{relative.as_posix()}", pattern) for pattern in patterns)


def test_sample_paths_from_simulated_site_packages(tmp_path):
    installed = tmp_path / "lib/python3.11/site-packages/autoassess"
    installed.mkdir(parents=True)
    shutil.copyfile(demo.__file__, installed / "demo.py")
    shutil.copytree(Path(demo.__file__).parent / "sample_exam", installed / "sample_exam")
    module = runpy.run_path(str(installed / "demo.py"))
    sample = module["SAMPLE"]
    assert sample == installed / "sample_exam"
    assert load_spec(sample / "exam_spec.yaml").exam_id
    assert (sample / "answer_sheets/S002.txt").is_file()
    assert (sample / "answer_sheets/S002_scan.pdf").is_file()


def test_scanned_sample_is_small_ruled_page_pdf():
    from tempfile import TemporaryDirectory

    from PIL import Image

    from autoassess.annotate import typeset
    from autoassess.pipeline import read_sheet

    scan = SAMPLE / "answer_sheets/S002_scan.pdf"
    assert scan.stat().st_size < 300_000
    with TemporaryDirectory() as work:
        expected = typeset(read_sheet(SAMPLE / "answer_sheets/S002.txt", None), Path(work), "S002")
        with pymupdf.open(scan) as pdf:
            assert len(pdf) == len(expected)
            # This is a scan path: image pages, without a hidden typed text layer.
            assert all(page.get_images() and not page.get_text().strip() for page in pdf)
            for page, source in zip(pdf, expected, strict=True):
                image = Image.open(source.image_path)
                pix = page.get_pixmap(dpi=150)
                assert abs(pix.width - image.width) <= 1
                assert abs(pix.height - image.height) <= 1


def test_demo_dependency_matches_tested_gradio_series():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "gradio>=6.30,<6.31" in config["project"]["optional-dependencies"]["demo"]
