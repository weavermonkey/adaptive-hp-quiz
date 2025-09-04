from pydantic import BaseModel
from typing import List, Optional

class Option(BaseModel):
    id: str
    text: str

class Question(BaseModel):
    id: str
    text: str
    options: List[Option]
    correct_option_id: str
    difficulty: str

class StartSessionResponse(BaseModel):
    session_id: str

class GetQuestionResponse(BaseModel):
    question: Question
    show_difficulty_change: Optional[str] = None

class SubmitAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    selected_option_id: str

class SubmitAnswerResponse(BaseModel):
    correct: bool
    difficulty: str
    correct_answer_text: Optional[str] = None
    window_completed: bool = False

class RecentWindowInfo(BaseModel):
    window_complete: bool
    recent_results: List[bool]
    recent_correct_count: int
    window_size: int
