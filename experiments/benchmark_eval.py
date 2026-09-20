import json
import asyncio
from src.evaluator import OpenRouterAssessmentPipeline
from src.evaluation.metrics import AssessmentMetrics

async def run_benchmark():
    print("=== Running Inter-Rater Reliability Benchmarks on Golden Set ===")
    with open("data/benchmarks/benchmark_dataset.json", "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    evaluator = OpenRouterAssessmentPipeline()
    human_scores = []
    model_scores = []

    for item in data:
        ref_sol = f"Comprehensive standard academic rubric solution for: {item['question']}"
        rubrics = [
            {"criterion": "Mathematical Accuracy", "max_marks": 5.0, "description": "Formulas and bounds"},
            {"criterion": "Conceptual Clarity", "max_marks": 5.0, "description": "Intuition and explanation"}
        ]
        res = await evaluator.evaluate_submission(item["student_text"], ref_sol, rubrics)
        awarded = res["assessment"]["score_awarded"]
        human_scores.append(item["human_grade"])
        model_scores.append(awarded)
        print(f"[{item['submission_id']}] Human: {item['human_grade']} | Model Judge: {awarded}")

    metrics = AssessmentMetrics.calculate_agreement(human_scores, model_scores)
    print("\n--- Benchmark Validation Results ---")
    for k, v in metrics.items():
        print(f"{k}: {v}")

    with open("experiments/benchmark_results.json", "w", encoding="utf-8-sig") as f:
        json.dump({"metrics": metrics, "human_scores": human_scores, "model_scores": model_scores}, f, indent=2)
    print("Results persisted to experiments/benchmark_results.json")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
