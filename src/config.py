import os
from pydantic import BaseModel

class SystemConfig(BaseModel):
    # API Endpoints & Keys
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    BODHAN_API_KEY: str = os.getenv("BODHAN_API_KEY", "")
    BODHAN_BASE_URL: str = os.getenv("BODHAN_BASE_URL", "https://api.bodhan.ai/v1")
    
    # Model Configurations
    DEFAULT_JUDGE_MODEL: str = os.getenv("DEFAULT_JUDGE_MODEL", "anthropic/claude-3.5-sonnet")
    CRITIC_MODEL: str = os.getenv("CRITIC_MODEL", "meta-llama/llama-3.1-70b-instruct")
    
    # OCR Settings
    OCR_LANGUAGES: list[str] = ["en", "hi", "ta", "te", "kn"]
    CONFIDENCE_THRESHOLD: float = 0.85

config = SystemConfig()
