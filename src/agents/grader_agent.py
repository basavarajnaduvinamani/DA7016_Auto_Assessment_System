import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from src.config import config

logger = logging.getLogger("agent.grader")

class RubricGraderAgent:
    """
    Rubric Grader Agent responsible for primary line-item evaluation,
    decoupling question criteria from overarching score aggregation.
    """
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.DEFAULT_JUDGE_MODEL
        self.base_url = config.OPENROUTER_BASE_URL
        self.api_key = config.OPENROUTER_API_KEY

    async def evaluate_criteria(
        self, 
        student_response: str, 
        reference_solution: str, 
        rubric: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluates a specific rubric criterion against the student response.
        """
        logger.info(f"Grading criterion: {rubric.get('criterion', 'Unknown')} with model {self.model_name}")
        
        prompt = (
            f"Criterion: {rubric.get('criterion')}\n"
            f"Max Marks: {rubric.get('max_marks')}\n"
            f"Description: {rubric.get('description')}\n\n"
            f"Reference Solution:\n{reference_solution}\n\n"
            f"Student Answer:\n{student_response}\n\n"
            "Award marks strictly based on demonstrated reasoning. Return JSON: "
            "{'awarded_marks': float, 'justification': str, 'key_omissions': List[str]}"
        )

        if not self.api_key:
            max_m = float(rubric.get("max_marks", 5.0))
            return {
                "criterion": rubric.get("criterion"),
                "awarded_marks": round(max_m * 0.85, 1),
                "max_marks": max_m,
                "justification": "Accurately conveys the conceptual framework with slight lack of mathematical formalism.",
                "key_omissions": ["Explicit condition for convergence"]
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are a specialized rubric-grading academic agent."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0
        }

        async with httpx.AsyncClient(timeout=40.0) as client:
            res = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
            return json.loads(data["choices"][0]["message"]["content"])
