"""Public landing page: shown before sign-in, numbers sourced from docs/report/numbers.md."""

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoassess.web.app import create_app
from autoassess.web.landing import CLASSROOM, REPO_URL, RESULTS

NUMBERS = Path(__file__).resolve().parents[1] / "docs" / "report" / "numbers.md"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")

    def blocked(*args, **kwargs):
        pytest.fail("Landing tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    with TestClient(create_app(tmp_path / "app", seed_samples=False)) as c:
        yield c


def test_landing_numbers_match_the_report():
    text = NUMBERS.read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip().strip("*"): line for line in text.splitlines() if line.startswith("| ")}
    ours = next(line for name, line in rows.items() if name.startswith("Final config"))
    for row, line in zip(RESULTS, [rows["Human vs human"], ours, rows["Lexical baseline (ablation run)"]], strict=True):
        for key in ("qwk", "ci", "mae", "within_1"):
            assert row[key] in line, (row["system"], key)
    assert f"QWK vs teacher | {CLASSROOM['qwk']} {CLASSROOM['ci']}" in text
    assert (
        f"{CLASSROOM['flagged']} questions" in text
        and f"{CLASSROOM['students']} students x 15 = {CLASSROOM['answers']}" in text
    )


def test_landing_is_public_and_leads_to_the_demo(client):
    response = client.get("/", follow_redirects=True)
    assert response.status_code == 200 and response.url.path == "/sign-in"
    page = response.text
    for text in (
        "Try the demo",
        "View on GitHub",
        REPO_URL,
        "selective auto-marking with teacher review",
        "0.723",
        "[0.667, 0.773]",
        "0.375",
        "QWK 0.47",
        "How it works",
        "example-redink.webp",
    ):
        assert text in page
    assert page.count('value="demo@redink.local"') == 2
    assert client.get("/static/landing.css").status_code == 200
    assert client.get("/static/example-redink.webp").headers["content-type"] == "image/webp"
    signed_in = client.post("/sign-in", data={"email": "demo@redink.local"})
    assert "Hello, Demo Teacher." in signed_in.text and "Try the demo" not in signed_in.text


def test_failed_sign_in_keeps_the_landing_page(client):
    response = client.post("/sign-in", data={"email": "nobody@example.org"})
    assert response.status_code == 400 and "recognise that email" in response.text and "How it works" in response.text


def test_grading_lab_uses_the_red_ink_brand(client):
    client.post("/sign-in", data={"email": "demo@redink.local"})
    assert "#ad343b" in client.get("/lab/theme.css").text
    config = client.get("/lab/config").json()
    assert "redink-bar" in config["css"]
    assert "Back to Red-Ink Classroom" in str(config["components"])
