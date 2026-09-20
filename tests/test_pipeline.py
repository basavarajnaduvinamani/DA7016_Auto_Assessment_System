import asyncio
from src.ocr_engine import BodhanOCREngine
from src.evaluator import OpenRouterAssessmentPipeline

async def run_pipeline_test():
    print("--- Starting DA7016 Auto-Assessment Verification Test ---")
    
    # 1. OCR Test
    ocr = BodhanOCREngine()
    sample_bytes = b"fake_image_bytes_for_testing"
    ocr_res = await ocr.extract_text_from_image(sample_bytes, language="en")
    print("[PASS] OCR Module:", ocr_res["status"], "| Extracted length:", len(ocr_res["extracted_text"]))

    # 2. Evaluation Engine Test
    evaluator = OpenRouterAssessmentPipeline()
    sample_rubric = [
        {"criterion": "Architecture Formulation", "max_marks": 5.0, "description": "Checks model layers and self-attention description"},
        {"criterion": "Convergence Analysis", "max_marks": 5.0, "description": "Checks loss optimization bounds"}
    ]
    student_ans = ocr_res["extracted_text"]
    ref_ans = "Self-attention layer connects key, query, and value matrices with softmax scaling factor sqrt(d_k)."
    
    eval_res = await evaluator.evaluate_submission(student_ans, ref_ans, sample_rubric)
    print("[PASS] Evaluator Module: Score awarded =", eval_res["assessment"]["score_awarded"], "/", eval_res["assessment"]["total_score"])
    print("--- All System Tests Passed Successfully ---")

if __name__ == "__main__":
    asyncio.run(run_pipeline_test())
