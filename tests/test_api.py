import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient

from autoassess.api import app
from conftest import SAMPLE

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_grade_baseline():
    files = {
        "spec": ("exam_spec.yaml", (SAMPLE / "exam_spec.yaml").read_bytes()),
        "sheet": ("S001.txt", (SAMPLE / "answer_sheets" / "S001.txt").read_bytes()),
    }
    r = client.post("/grade", files=files, data={"mode": "baseline", "student_id": "S001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grade"]["student_id"] == "S001" and len(body["grade"]["questions"]) == 3
    assert body["html"].startswith("<!doctype html>")


def test_bad_spec_is_422():
    files = {"spec": ("s.yaml", b"exam_id: x\nquestions: []"), "sheet": ("a.txt", b"Q1 hi")}
    assert client.post("/grade", files=files, data={"mode": "baseline"}).status_code == 422
