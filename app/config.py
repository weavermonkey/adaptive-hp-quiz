import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    prefetch_on_start: bool = os.getenv("PREFETCH_ON_START", "true").lower() == "true"
    question_batch_size: int = int(os.getenv("QUESTION_BATCH_SIZE", "10"))
    answer_window: int = int(os.getenv("ANSWER_WINDOW", "5"))

settings = Settings()
