from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import ORJSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import uuid
from time import perf_counter
from datetime import datetime
from zoneinfo import ZoneInfo
from .state import session_store
from .models import StartSessionResponse, GetQuestionResponse, SubmitAnswerRequest, SubmitAnswerResponse
from .services.adaptive_engine import determine_next_difficulty
from .services.gemini_client import GeminiQuestionGenerator
from .config import settings

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("adaptive_hp_quiz")

app = FastAPI(default_response_class=ORJSONResponse)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

generator = GeminiQuestionGenerator()

class StartSessionRequest(BaseModel):
	user_id: str | None = None

class DebugPromptResponse(BaseModel):
	prompt: str

authorization_placeholder = None

@app.on_event("startup")
def on_startup() -> None:
	ist_time = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
	logger.info({
		"event": "api_startup",
		"ist_time": ist_time,
		"model": settings.gemini_model,
		"batch_size": settings.question_batch_size,
		"answer_window": settings.answer_window,
	})

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
	start = perf_counter()
	response = await call_next(request)
	duration_ms = int((perf_counter() - start) * 1000)
	logger.debug({
		"event": "request_timing",
		"method": request.method,
		"path": request.url.path,
		"status_code": response.status_code,
		"duration_ms": duration_ms,
	})
	return response

@app.post("/api/session/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest | None = None):
	session_id = str(uuid.uuid4())
	session_store.create_session(session_id)
	logger.debug({"event": "session_started", "session_id": session_id})
	if settings.prefetch_on_start:
		try:
			gen_start = perf_counter()
			questions = generator.generate_questions(
				difficulty="medium",
				history=[],
				target="baseline",
				count=settings.question_batch_size,
				asked_texts=session_store.get_asked_texts(session_id),
				correct_examples=session_store.get_correct_texts(session_id),
				wrong_examples=session_store.get_wrong_texts(session_id),
				user_filters=None,
			)
			session_store.set_question_buffer(session_id, questions)
			logger.debug({
				"event": "prefetch_done",
				"session_id": session_id,
				"count": len(questions),
				"duration_ms": int((perf_counter() - gen_start) * 1000),
			})
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
		correct_texts = session_store.get_correct_texts(session_id)
		wrong_texts = session_store.get_wrong_texts(session_id)
		target = "harder" if session_store.should_increase(session_id) else "easier" if session_store.should_decrease(session_id) else "baseline"
		try:
			gen_start = perf_counter()
			generated = generator.generate_questions(
				difficulty=difficulty,
				history=history,
				target=target,
				count=settings.question_batch_size,
				asked_texts=asked_texts,
				correct_examples=correct_texts,
				wrong_examples=wrong_texts,
				user_filters=None,
				session_id=session_id,
			)
			session_store.set_question_buffer(session_id, generated)
			logger.debug({
				"event": "generated_questions",
				"session_id": session_id,
				"target": target,
				"difficulty": difficulty,
				"count": len(generated),
				"duration_ms": int((perf_counter() - gen_start) * 1000),
				"asked_count": len(asked_texts),
				"correct_count": len(correct_texts),
				"wrong_count": len(wrong_texts),
			})
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
		asked_texts = session_store.get_avoid_texts(payload.session_id)
		correct_texts = session_store.get_correct_texts(payload.session_id)
		wrong_texts = session_store.get_wrong_texts(payload.session_id)
		target = "harder" if direction == "increase" else "easier" if direction == "decrease" else "baseline"
		try:
			gen_start = perf_counter()
			generated = generator.generate_questions(
				difficulty=difficulty,
				history=history,
				target=target,
				count=settings.question_batch_size,
				asked_texts=asked_texts,
				correct_examples=correct_texts,
				wrong_examples=wrong_texts,
				user_filters=None,
				session_id=payload.session_id,
			)
			session_store.set_question_buffer(payload.session_id, generated)
			logger.debug({
				"event": "regenerated_after_window",
				"session_id": payload.session_id,
				"direction": direction,
				"difficulty": difficulty,
				"count": len(generated),
				"duration_ms": int((perf_counter() - gen_start) * 1000),
				"asked_count": len(asked_texts),
				"correct_count": len(correct_texts),
				"wrong_count": len(wrong_texts),
			})
		except Exception:
			logger.exception("generation_after_window_failed")
	try:
		served = session_store.get_served_question(payload.session_id, payload.question_id)
		question_text = served.text if served else None
		selected_text = next((o.text for o in (served.options if served else []) if o.id == payload.selected_option_id), None)
		correct_text = next((o.text for o in (served.options if served else []) if o.id == (served.correct_option_id if served else "")), None)
		import asyncio
		asyncio.get_event_loop().run_until_complete(generator.log_user_answer(payload.session_id, question_text, selected_text, correct_text, is_correct))
	except Exception:
		logger.debug({"event": "answer_log_failed"})
	return SubmitAnswerResponse(correct=is_correct, difficulty=session_store.get_difficulty(payload.session_id))

@app.get("/api/debug/prompt", response_model=DebugPromptResponse)
def get_debug_prompt(session_id: str, target: str | None = None, difficulty: str | None = None):
	if not session_store.has_session(session_id):
		raise HTTPException(status_code=404, detail="session_not_found")
	diff = difficulty or session_store.get_difficulty(session_id)
	asked_texts = session_store.get_asked_texts(session_id)
	correct_texts = session_store.get_correct_texts(session_id)
	wrong_texts = session_store.get_wrong_texts(session_id)
	chosen_target = target or ("harder" if session_store.should_increase(session_id) else "easier" if session_store.should_decrease(session_id) else "baseline")
	prompt = generator._build_prompt(
		difficulty=diff,
		history=session_store.get_recent_history(session_id),
		target=chosen_target,
		asked_texts=asked_texts,
		correct_examples=correct_texts,
		wrong_examples=wrong_texts,
		user_filters=None,
	)
	return DebugPromptResponse(prompt=prompt)
