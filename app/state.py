import uuid
from collections import deque
from typing import Dict, Deque, List, Optional, Set
from .models import Question, Option, RecentWindowInfo
from .config import settings

class SessionData:
    def __init__(self) -> None:
        self.difficulty = "medium"
        self.questions: Deque[Question] = deque()
        self.answered: Dict[str, bool] = {}
        self.recent_results: Deque[bool] = deque(maxlen=settings.answer_window)
        self.pending_popup: Optional[str] = None
        self.served_unanswered: Dict[str, Question] = {}
        self.asked_question_ids: Set[str] = set()
        self.asked_question_texts: Set[str] = set()

class SessionStore:
    def __init__(self) -> None:
        self.sessions: Dict[str, SessionData] = {}

    def create_session(self, session_id: str) -> None:
        self.sessions[session_id] = SessionData()

    def has_session(self, session_id: str) -> bool:
        return session_id in self.sessions

    def get_difficulty(self, session_id: str) -> str:
        return self.sessions[session_id].difficulty

    def set_question_buffer(self, session_id: str, questions: List[Question]) -> None:
        filtered = self._filter_new(session_id, questions)
        self.sessions[session_id].questions = deque(filtered)

    def extend_question_buffer(self, session_id: str, questions: List[Question]) -> None:
        filtered = self._filter_new(session_id, questions)
        self.sessions[session_id].questions.extend(filtered)

    def pop_next_question(self, session_id: str) -> Optional[Question]:
        if self.sessions[session_id].questions:
            q = self.sessions[session_id].questions.popleft()
            self.sessions[session_id].served_unanswered[q.id] = q
            self.sessions[session_id].asked_question_ids.add(q.id)
            self.sessions[session_id].asked_question_texts.add(q.text)
            return q
        return None

    def get_served_question(self, session_id: str, question_id: str) -> Optional[Question]:
        return self.sessions[session_id].served_unanswered.get(question_id)

    def evaluate_answer(self, session_id: str, question_id: str, selected_option_id: str) -> bool:
        q = self.sessions[session_id].served_unanswered.get(question_id)
        if q is None:
            return False
        return selected_option_id == q.correct_option_id

    def record_answer(self, session_id: str, question_id: str, is_correct: bool) -> RecentWindowInfo:
        self.sessions[session_id].answered[question_id] = is_correct
        if question_id in self.sessions[session_id].served_unanswered:
            self.sessions[session_id].served_unanswered.pop(question_id, None)
        self.sessions[session_id].recent_results.append(is_correct)
        recent = list(self.sessions[session_id].recent_results)
        return RecentWindowInfo(
            window_complete=len(recent) == settings.answer_window,
            recent_results=recent,
            recent_correct_count=sum(1 for r in recent if r),
            window_size=settings.answer_window,
        )

    def should_increase(self, session_id: str) -> bool:
        recent = self.sessions[session_id].recent_results
        return len(recent) == settings.answer_window and sum(1 for r in recent if r) >= settings.answer_window - 1

    def should_decrease(self, session_id: str) -> bool:
        recent = self.sessions[session_id].recent_results
        return len(recent) == settings.answer_window and sum(1 for r in recent if r) <= 1

    def adjust_difficulty(self, session_id: str, direction: str) -> None:
        order = ["easy", "medium", "hard"]
        current = self.sessions[session_id].difficulty
        idx = order.index(current)
        if direction == "increase" and idx < len(order) - 1:
            self.sessions[session_id].difficulty = order[idx + 1]
        elif direction == "decrease" and idx > 0:
            self.sessions[session_id].difficulty = order[idx - 1]
        self.sessions[session_id].recent_results.clear()

    def set_pending_popup(self, session_id: str, direction: str) -> None:
        if direction == "increase":
            self.sessions[session_id].pending_popup = "too_easy_increasing_difficulty"
        elif direction == "decrease":
            self.sessions[session_id].pending_popup = "too_hard_decreasing_difficulty"
        else:
            self.sessions[session_id].pending_popup = None

    def consume_pending_popup(self, session_id: str) -> Optional[str]:
        value = self.sessions[session_id].pending_popup
        self.sessions[session_id].pending_popup = None
        return value

    def get_recent_history(self, session_id: str) -> List[bool]:
        return list(self.sessions[session_id].recent_results)

    def get_asked_texts(self, session_id: str) -> List[str]:
        return list(self.sessions[session_id].asked_question_texts)

    def _filter_new(self, session_id: str, candidates: List[Question]) -> List[Question]:
        seen_ids = self.sessions[session_id].asked_question_ids
        seen_texts = self.sessions[session_id].asked_question_texts
        unique: List[Question] = []
        for q in candidates:
            if q.id in seen_ids or q.text in seen_texts:
                continue
            unique.append(q)
        return unique

session_store = SessionStore()
