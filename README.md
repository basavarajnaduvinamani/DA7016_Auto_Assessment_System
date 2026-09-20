# DA7016: Multi-Agent Auto-Assessment & Handwritten Evaluation Pipeline

[![IIT Madras](https://img.shields.io/badge/IIT%20Madras-DA7016%20Course%20Project-0066CC.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production%20Engine-009688.svg)](https://fastapi.tiangolo.com/)
[![Bodhan.AI](https://img.shields.io/badge/AI4Bharat-Bodhan.AI%20OCR-orange.svg)](https://console.bodhan.ai/)
[![OpenRouter](https://img.shields.io/badge/LLM--as--a--Judge-OpenRouter%20API-7928CA.svg)](https://openrouter.ai/)
[![CI](https://img.shields.io/badge/CI%2FCD-Passing-brightgreen.svg)](#)

An institutional-grade, multi-agent automated assessment and handwriting grading pipeline built for **DA7016: Recent Advances in Generative AI** at the **Indian Institute of Technology Madras** (Course Advisor: Prof. Mitesh M. Khapra).

The system addresses subjective grading drift and scale limitations in academic assessments by combining **Bodhan.AI (AI4Bharat)** high-fidelity document OCR with a **Deliberative Multi-Agent LLM-as-a-Judge** framework (Rubric Grader + Adversarial Critic).

---

## 🏛️ System Architecture

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
   ┌────────────────────────────────────────────────────────────────────────┐
   │                  Deliberative Multi-Agent Architecture                 │
   │                                                                        │
   │   ┌────────────────────────────────┐   Draft Marks    ┌────────────┐   │
   │   │     Rubric Grader Agent        │─────────────────▶│ Adversarial│   │
   │   │  (Granular Line-Item Scoring)  │                  │   Critic   │   │
   │   └────────────────────────────────┘                  │   Agent    │   │
   │                   ▲                                   └─────┬──────┘   │
   │                   │                                         │          │
   │                   │             Audited & Calibrated        │          │
   │                   └─────────────────────────────────────────┘          │
   │                                           │                            │
   │                                           ▼                            │
   │                           OpenRouter Model Router                      │
   │                    (Claude 3.5 Sonnet / LLaMA 3.1 70B)                 │
   └───────────────────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                               ┌─────────────────────────────┐
                               │ Structured Assessment Sheet │
                               │  • Criterion Breakdown     │
                               │  • Inter-Rater Reliability  │
                               │  • Deliberative Feedback    │
                               └─────────────────────────────┘
```

---

## 🔬 Core Technical Modules

### 1. Bodhan.AI Handwriting & Indian Script OCR (`src/ocr_engine.py`)
- Direct integration with AI4Bharat's Bodhan API Router for Indian handwriting recognition and bilingual structural parsing.

### 2. Multi-Agent Evaluation & Auditing (`src/agents/`)
- **`RubricGraderAgent` (`src/agents/grader_agent.py`)**: Deconstructs questions into atomic grading criteria and matches student conceptual formulations against reference rubrics.
- **`AdversarialCriticAgent` (`src/agents/critic_agent.py`)**: Audits awarded grades for leniency bias, enforces rigorous penalties for ungrounded assertions/hallucinations, and prevents grade inflation.

### 3. Rigorous Evaluation Benchmarks (`experiments/` & `src/evaluation/`)
- Computes **Inter-Rater Reliability (IRR)** including **Quadratic Weighted Kappa (QWK)** and **Mean Absolute Error (MAE)** against human TA ground truth (`data/benchmarks/benchmark_dataset.json`).

---

## 📁 Repository Structure

```text
├── .github/
│   └── workflows/
│       └── ci.yml               # Automated CI verification workflow
├── data/
│   └── benchmarks/
│       └── benchmark_dataset.json # Ground-truth human-annotated evaluations
├── experiments/
│   ├── benchmark_eval.py        # Model agreement & IRR benchmark harness
│   └── benchmark_results.json   # Logged evaluation metrics
├── src/
│   ├── agents/
│   │   ├── grader_agent.py      # Line-item rubric grading agent
│   │   └── critic_agent.py      # Adversarial anti-inflation critic agent
│   ├── evaluation/
│   │   └── metrics.py           # Statistical metrics (Kappa, MSE, Pearson)
│   ├── config.py                # OpenRouter and Bodhan.AI routing config
│   ├── evaluator.py             # Orchestration pipeline
│   ├── ocr_engine.py            # Bodhan.AI OCR interface
│   └── main.py                  # Production FastAPI service
├── tests/
│   └── test_pipeline.py         # End-to-end integration tests
├── requirements.txt             # Project dependencies
└── README.md                    # Institutional documentation
```

---

## ⚡ Setup & Execution

### 1. Installation
```bash
git clone https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System.git
cd DA7016_Auto_Assessment_System
pip install -r requirements.txt
```

### 2. Run Pipeline Integration Tests
```bash
python -m tests.test_pipeline
```

### 3. Run Benchmark Harness
```bash
python -m experiments.benchmark_eval
```

### 4. Launch FastAPI Service
```bash
uvicorn src.main:app --reload --port 8000
```
Interactive docs: `http://localhost:8000/docs`

---

## 👨‍💻 Course & Author Information

* **Student:** Basavaraj A Naduvinamani (Roll No: `DA25C005`)
* **Program:** Joint M.Sc. in Data Science and Artificial Intelligence
* **Institution:** Indian Institute of Technology Madras & University of Birmingham
* **Course:** DA7016: Recent Advances in Generative AI (Jul–Nov 2026 Semester)
* **Advisor:** Prof. Mitesh M. Khapra
