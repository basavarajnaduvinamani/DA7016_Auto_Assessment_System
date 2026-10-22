# DA7016: Course Project Interim Report & Architecture Specification

* **Course Code:** DA7016: Recent Advances in Generative AI
* **Semester:** July – November 2026
* **Department:** Department of Data Science and Artificial Intelligence, IIT Madras
* **Course Instructor:** Prof. Mitesh M. Khapra
* **Student Name:** Basavaraj A Naduvinamani
* **Roll Number:** DA25C005

---

## 1. Project Title
**Multi-Agent Auto-Assessment and Handwriting Evaluation System for Technical Submissions**

## 2. Problem Statement & Motivation
Manual evaluation of technical handwritten assessments in large academic courses introduces subjective grading variability, human fatigue, and significant turn-around delays. 
Existing automated evaluation systems rely largely on rudimentary surface-level lexical matching (n-gram overlap) or basic sentence embeddings, which fail to evaluate mathematical reasoning, step-by-step logic, and domain-specific correctness. Furthermore, standard OCR engines struggle with handwritten technical scripts and multilingual text in Indian educational environments.

## 3. Objectives & Core Modules
1. **High-Fidelity Handwritten OCR:**
   - Integrate **Bodhan.AI (AI4Bharat)** API Router to extract text, mathematical symbols, and structural layout from scanned student answer scripts across English and regional languages.
2. **Multi-Agent Evaluation (LLM-as-a-Judge):**
   - Implement a decoupled evaluation workflow using **OpenRouter API** to orchestrate:
     - *Rubric Grader Agent:* Performs line-item evaluation against reference rubrics.
     - *Adversarial Critic Agent:* Audits proposed grades for leniency bias, enforces penalties for hallucinations, and ensures calibrated score outputs.
3. **Automated Inter-Rater Reliability (IRR) Benchmarking:**
   - Validate model alignment against human-graded benchmarks using Quadratic Weighted Kappa (QWK) and Mean Absolute Error (MAE).

## 4. System Implementation & Infrastructure
* **Compute & API Infrastructure:** Personal course-allotted OpenRouter API credits ($20 USD) & Bodhan.AI developer account.
* **Backend:** Python 3.10+, FastAPI asynchronous REST endpoints.
* **Demonstration UI:** Streamlit interactive dashboard (`app.py`) for live test submissions and rubric reviews.

## 5. Current Progress & Project Status
* [x] Course project requirements submitted and approved.
* [x] Bodhan.AI API credentials and OpenRouter access configured.
* [x] Core architecture implemented: OCR client, multi-agent grading pipeline, adversarial critic, and FastAPI endpoints.
* [x] Streamlit demo interface built for document uploading and real-time grading.
* [ ] Expanded fine-grained handwritten test-set evaluation and rubric calibration (in progress).

---
*Report submitted as part of the continuous assessment and placement verification documentation for DA7016.*
