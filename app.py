import streamlit as st
import asyncio
from src.ocr_engine import BodhanOCREngine
from src.evaluator import OpenRouterAssessmentPipeline

st.set_page_config(
    page_title="DA7016 Auto-Assessment System",
    page_icon="🎓",
    layout="wide"
)

st.title("🎓 Multi-Agent Auto-Assessment & Grading Pipeline")
st.caption("DA7016: Recent Advances in Generative AI | IIT Madras | Basavaraj A Naduvinamani (DA25C005)")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Submission & Reference Input")
    eval_mode = st.radio("Input Source", ["Text Submission", "Scanned Answer Sheet (OCR)"])
    
    student_text = ""
    if eval_mode == "Text Submission":
        student_text = st.text_area("Student Response", height=180, value="Multi-head attention projects queries, keys, and values into multiple representation subspaces...")
    else:
        uploaded_file = st.file_uploader("Upload Scanned Answer Sheet", type=["png", "jpg", "jpeg", "pdf"])
        if uploaded_file:
            st.image(uploaded_file, caption="Uploaded Sheet", use_column_width=True)
            if st.button("Run Bodhan.AI OCR Extraction"):
                with st.spinner("Extracting handwritten text via Bodhan.AI..."):
                    ocr = BodhanOCREngine()
                    res = asyncio.run(ocr.extract_text_from_image(uploaded_file.getvalue()))
                    student_text = res.get("extracted_text", "")
                    st.success("Extracted text successfully!")
                    st.text_area("OCR Result", value=student_text, height=120)

    reference_text = st.text_area("Reference Solution / Key Points", height=120, value="Standard reference solution explaining query-key dot products, scaling factors, and subspace projections.")

with col2:
    st.subheader("2. Evaluation Rubrics & Execution")
    c1 = st.text_input("Criterion 1", "Mathematical Formulation")
    m1 = st.number_input("Max Marks 1", 1.0, 20.0, 5.0)
    
    c2 = st.text_input("Criterion 2", "Conceptual Depth & Clarity")
    m2 = st.number_input("Max Marks 2", 1.0, 20.0, 5.0)

    if st.button("🚀 Evaluate Submission via Multi-Agent Pipeline", type="primary"):
        with st.spinner("Orchestrating Grader Agent and Adversarial Critic via OpenRouter..."):
            evaluator = OpenRouterAssessmentPipeline()
            rubrics = [
                {"criterion": c1, "max_marks": m1, "description": "Formulation accuracy"},
                {"criterion": c2, "max_marks": m2, "description": "Explanation clarity"}
            ]
            result = asyncio.run(evaluator.evaluate_submission(student_text, reference_text, rubrics))
            
            assessment = result.get("assessment", {})
            st.metric("Total Score", f"{assessment.get('score_awarded', 0)} / {assessment.get('total_score', 10)}")
            
            st.write("### Criterion Breakdown")
            for item in assessment.get("criterion_breakdown", []):
                st.write(f"- **{item['criterion']}**: `{item['marks_awarded']} / {item['max_marks']}` — *{item['evaluator_comment']}*")

            st.write("### Evaluator Deliberation")
            st.info(assessment.get("deliberative_justification", ""))
