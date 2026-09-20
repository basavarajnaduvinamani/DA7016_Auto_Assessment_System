from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json

from src.ocr_engine import BodhanOCREngine
from src.evaluator import OpenRouterAssessmentPipeline

app = FastAPI(
    title="DA7016: Multi-Agent Auto-Assessment Pipeline",
    description="AI-driven assessment and rubric grading system integrating Bodhan.AI OCR & OpenRouter LLM-as-a-Judge.",
    version="1.0.0"
)

ocr_service = BodhanOCREngine()
evaluator_service = OpenRouterAssessmentPipeline()

class TextEvaluationRequest(BaseModel):
    student_answer: str
    reference_answer: str
    rubrics: Optional[List[Dict[str, Any]]] = None

@app.get("/")
def root():
    return {
        "course": "DA7016: Recent Advances in Generative AI",
        "institution": "Indian Institute of Technology Madras",
        "project": "Multi-Agent Auto-Assessment & Handwriting Evaluation System",
        "status": "Active / Operational",
        "version": "1.0.0"
    }

@app.post("/api/evaluate-text")
async def evaluate_text(payload: TextEvaluationRequest):
    result = await evaluator_service.evaluate_submission(
        student_answer=payload.student_answer,
        reference_answer=payload.reference_answer,
        rubrics=payload.rubrics or []
    )
    return result

@app.post("/api/evaluate-sheet")
async def evaluate_scanned_sheet(
    image: UploadFile = File(...),
    reference_answer: str = Form(...),
    rubrics_json: Optional[str] = Form(None),
    language: str = Form("en")
):
    try:
        image_content = await image.read()
        ocr_result = await ocr_service.extract_text_from_image(image_content, language=language)
        extracted_text = ocr_result.get("extracted_text", "")

        rubrics = json.loads(rubrics_json) if rubrics_json else []
        evaluation_result = await evaluator_service.evaluate_submission(
            student_answer=extracted_text,
            reference_answer=reference_answer,
            rubrics=rubrics
        )

        return {
            "ocr_extraction": ocr_result,
            "grading_evaluation": evaluation_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
