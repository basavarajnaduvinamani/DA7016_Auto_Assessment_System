# DA7016: Multi-Agent Auto-Assessment & Handwritten Evaluation Pipeline

[![IIT Madras](https://img.shields.io/badge/IIT%20Madras-DA7016%20Course%20Project-0066CC.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production%20Engine-009688.svg)](https://fastapi.tiangolo.com/)
[![Bodhan.AI](https://img.shields.io/badge/AI4Bharat-Bodhan.AI%20OCR-orange.svg)](https://console.bodhan.ai/)
[![OpenRouter](https://img.shields.io/badge/LLM--as--a--Judge-OpenRouter%20API-7928CA.svg)](https://openrouter.ai/)
[![Status](https://img.shields.io/badge/Status-Active%20%2F%20Operational-brightgreen.svg)](#)

An intelligent, multi-agent automated assessment and handwriting grading pipeline designed for **DA7016: Recent Advances in Generative AI** at the **Indian Institute of Technology Madras** (Supervised under Prof. Mitesh M. Khapra).

The system automates objective, criterion-driven grading of scanned handwritten submissions and answers using state-of-the-art regional document OCR and a deliberative multi-agent LLM-as-a-Judge architecture.

---

## 🎯 System Architecture & Pipeline

```
                     ┌─────────────────────────────┐
                     │ Scanned Handwritten Answer   │
                     │      Sheets / Images        │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │   Bodhan.AI (AI4Bharat)     │
                     │  High-Fidelity OCR Engine   │
                     │ (Supports Indian Scripts)   │
                     └──────────────┬──────────────┘
                                    │ Extracted Text & Layout
                                    ▼
   ┌─────────────────────────────────────────────────────────────┐
   │              Multi-Agent Evaluation Framework               │
   │  ┌────────────────────────┐     ┌────────────────────────┐  │
   │  │   Rubric Alignment     │────▶│   Adversarial Critic   │  │
   │  │        Agent           │     │         Agent          │  │
   │  └───────────┬────────────┘     └───────────┬────────────┘  │
   │              │                              │               │
   │              └──────────────┬───────────────┘               │
   │                             ▼                               │
   │                 OpenRouter LLM Inference                     │
   │          (Claude 3.5 Sonnet / LLaMA 3.1 70B)                 │
   └─────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
                     ┌─────────────────────────────┐
                     │ Structured Assessment Sheet │
                     │  • Criterion Breakdown     │
                     │  • Calibrated Numerical Gr. │
                     │  • Deliberative Feedback    │
                     └─────────────────────────────┘
```

---

## 🚀 Key Features

1. **Multimodal Handwritten Document Processing**:
   - Integrated with **Bodhan.AI (AI4Bharat API Router)** for character recognition and semantic structure preservation across English and multilingual handwritten exams.

2. **Deliberative Multi-Agent LLM-as-a-Judge**:
   - Operates a 2-stage verification system:
     - **Grader Agent**: Computes granular line-item rubric matching against golden reference solutions.
     - **Adversarial Critic**: Audits numerical boundaries, penalizes factual hallucinations, and prevents grade inflation.

3. **Rubric Alignment & Explainable Feedback**:
   - Produces structured JSON scorecards with point-by-point justifications, qualitative strengths, and specific remedial feedback for students.

4. **Production-Ready REST API**:
   - Built on **FastAPI** with async execution and complete Pydantic schema validation for batch evaluation.

---

## 🛠️ Tech Stack

* **Backend & API:** Python 3.10+, FastAPI, Uvicorn, Pydantic, HTTPX
* **OCR & Vision Engine:** Bodhan.AI (AI4Bharat OCR API Router)
* **LLM Engine:** OpenRouter API (Claude 3.5 Sonnet, LLaMA 3.1 70B Instruct)
* **Evaluation & Metrics:** Deterministic Rubric Alignment, Automated Error Bounds

---

## 📁 Repository Structure

```text
├── src/
│   ├── __init__.py
│   ├── config.py             # OpenRouter and Bodhan.AI routing configurations
│   ├── ocr_engine.py         # Bodhan OCR client for scanned handwriting extraction
│   ├── evaluator.py          # Multi-agent LLM-as-a-Judge grading pipeline
│   └── main.py               # FastAPI application endpoints
├── tests/
│   └── test_pipeline.py      # Automated pipeline verification suite
├── requirements.txt          # Production environment dependencies
└── README.md                 # Technical specification and documentation
```

---

## ⚡ Quick Start

### 1. Installation
```bash
git clone https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System.git
cd DA7016_Auto_Assessment_System
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
OPENROUTER_API_KEY=your_openrouter_api_key
BODHAN_API_KEY=your_bodhan_api_key
DEFAULT_JUDGE_MODEL=anthropic/claude-3.5-sonnet
```

### 3. Run Pipeline Tests
```bash
python -m tests.test_pipeline
```

### 4. Start the API Server
```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000/docs` for the interactive Swagger API documentation.

---

## 👨‍💻 Author & Course Affiliation

* **Student:** Basavaraj A Naduvinamani (Roll No: `DA25C005`)
* **Course:** DA7016: Recent Advances in Generative AI (July - Nov 2026 Semester)
* **Institution:** Department of Data Science and Artificial Intelligence, Indian Institute of Technology Madras
