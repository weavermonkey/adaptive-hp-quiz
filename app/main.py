from fastapi import FastAPI, HTTPException
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
import logging
import uuid
from .state import session_store
from .models import StartSessionResponse, GetQuestionResponse, SubmitAnswerRequest, SubmitAnswerResponse
from .services.adaptive_engine import determine_next_difficulty
from .services.gemini_client import GeminiQuestionGenerator
from .config import settings

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("adaptive_hp_quiz")

app = FastAPI(default_response_class=ORJSONResponse)

generator = GeminiQuestionGenerator()

class StartSessionRequest(BaseModel):
	user_id: str | None = None

@app.post("/api/session/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest | None = None):
	session_id = str(uuid.uuid4())
	session_store.create_session(session_id)
	logger.debug({"event": "session_started", "session_id": session_id})
	if settings.prefetch_on_start:
		try:
			questions = generator.generate_questions(difficulty="medium", history=[], target="baseline", count=settings.question_batch_size, asked_texts=session_store.get_asked_texts(session_id), correct_examples=[], wrong_examples=[], user_filters=None)
			session_store.set_question_buffer(session_id, questions)
			logger.debug({"event": "prefetch_done", "session_id": session_id, "count": len(questions)})
		except Exception as e:
			logger.exception("prefetch_failed")
	return StartSessionResponse(session_id=session_id)

@app.get("/api/quiz/next", response_model=GetQuestionResponse)
def get_next_question(session_id: str):
	if not session_store.has_session(session_id):
		raise HTTPException(status_code=404, detail="session_not_found")
	question = session_store.pop_next_question(session_id)
	if question is None:
		difficulty = session_store.get_difficulty(session_id)
		history = session_store.get_recent_history(session_id)
		asked_texts = session_store.get_asked_texts(session_id)
		target = "harder" if session_store.should_increase(session_id) else "easier" if session_store.should_decrease(session_id) else "baseline"
		try:
			generated = generator.generate_questions(difficulty=difficulty, history=history, target=target, count=settings.question_batch_size, asked_texts=asked_texts, correct_examples=[], wrong_examples=[], user_filters=None)
			session_store.set_question_buffer(session_id, generated)
			logger.debug({"event": "generated_questions", "session_id": session_id, "target": target, "difficulty": difficulty, "count": len(generated)})
		except Exception:
			logger.exception("generation_failed")
			raise HTTPException(status_code=500, detail="generation_failed")
		question = session_store.pop_next_question(session_id)
	logger.debug({
		"event": "serve_question",
		"session_id": session_id,
		"question_id": question.id,
		"difficulty": question.difficulty,
		"text": question.text,
		"options": [{"id": o.id, "text": o.text} for o in question.options],
	})
	return GetQuestionResponse(question=question, show_difficulty_change=session_store.consume_pending_popup(session_id))

@app.post("/api/quiz/submit", response_model=SubmitAnswerResponse)
def submit_answer(payload: SubmitAnswerRequest):
	if not session_store.has_session(payload.session_id):
		raise HTTPException(status_code=404, detail="session_not_found")
	served = session_store.get_served_question(payload.session_id, payload.question_id)
	is_correct = session_store.evaluate_answer(payload.session_id, payload.question_id, payload.selected_option_id)
	updated = session_store.record_answer(payload.session_id, payload.question_id, is_correct)
	logger.debug({
		"event": "submit_answer",
		"session_id": payload.session_id,
		"question_id": payload.question_id,
		"is_correct": is_correct,
		"selected_option_id": payload.selected_option_id,
		"correct_option_id": served.correct_option_id if served else None,
		"question_text": served.text if served else None,
		"selected_text": next((o.text for o in (served.options if served else []) if o.id == payload.selected_option_id), None),
		"correct_text": next((o.text for o in (served.options if served else []) if o.id == (served.correct_option_id if served else "")), None),
		"streak": updated.recent_correct_count,
		"window": updated.window_size,
	})
	if updated.window_complete:
		direction = determine_next_difficulty(updated.recent_results)
		session_store.adjust_difficulty(payload.session_id, direction)
		session_store.set_pending_popup(payload.session_id, direction)
		difficulty = session_store.get_difficulty(payload.session_id)
		history = session_store.get_recent_history(payload.session_id)
		asked_texts = session_store.get_asked_texts(payload.session_id)
		target = "harder" if direction == "increase" else "easier" if direction == "decrease" else "baseline"
		try:
			generated = generator.generate_questions(difficulty=difficulty, history=history, target=target, count=settings.question_batch_size, asked_texts=asked_texts, correct_examples=[], wrong_examples=[], user_filters=None)
			# Replace buffer to prioritize new difficulty set
			session_store.set_question_buffer(payload.session_id, generated)
			logger.debug({"event": "regenerated_after_window", "session_id": payload.session_id, "direction": direction, "difficulty": difficulty, "count": len(generated)})
		except Exception:
			logger.exception("generation_after_window_failed")
	return SubmitAnswerResponse(correct=is_correct, difficulty=session_store.get_difficulty(payload.session_id))
