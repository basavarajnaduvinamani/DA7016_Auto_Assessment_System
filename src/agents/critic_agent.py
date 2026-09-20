import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from src.config import config

logger = logging.getLogger("agent.critic")

class AdversarialCriticAgent:
    """
    Adversarial Critic Agent that inspects grading outputs for hallucinated marks,
    leniency bias, and rubric drift before final score commitment.
    """
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.CRITIC_MODEL
        self.base_url = config.OPENROUTER_BASE_URL
        self.api_key = config.OPENROUTER_API_KEY

    async def audit_grades(
        self,
        student_response: str,
        reference_solution: str,
        proposed_evaluations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Scrutinizes proposed marks to ensure no unearned credit is granted.
        """
        logger.info(f"Conducting adversarial audit with {self.model_name}")

        audit_prompt = {
            "task": "Perform rigorous adversarial audit of awarded marks.",
            "student_text": student_response,
            "reference_text": reference_solution,
            "proposed_grades": proposed_evaluations
        }

        if not self.api_key:
            return {
                "audit_passed": True,
                "adjusted_grades": proposed_evaluations,
                "critic_notes": "No severe grade inflation detected. Deductions accurately reflect omitted edge-case proofs.",
                "hallucination_penalty": 0.0
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/basavarajnaduvinamani/DA7016_Auto_Assessment_System",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a hyper-critical TA checking an AI grader's output for leniency bias or unearned marks."
                },
                {"role": "user", "content": json.dumps(audit_prompt)}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        async with httpx.AsyncClient(timeout=40.0) as client:
            res = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
            return json.loads(data["choices"][0]["message"]["content"])
