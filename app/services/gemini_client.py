import os
import json
import uuid
import random
from typing import List, Dict, Any
import logging
from datetime import datetime, timezone
import google.generativeai as genai
from time import perf_counter
from ..config import settings
from ..models import Question, Option
from .prompt_builder import PromptBuilder

logger = logging.getLogger("adaptive_hp_quiz")

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'logs')
LOG_DIR = os.path.abspath(LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)

class GeminiQuestionGenerator:
    def __init__(self) -> None:
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model
        self.generation_config = {
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 50,
            "response_mime_type": "application/json",
        }
        self.prompt_builder = PromptBuilder()
        try:
            self.model_for_tokens = genai.GenerativeModel(self.model_name)
        except Exception:
            self.model_for_tokens = None

    def _session_log_path(self, session_id: str) -> str:
        return os.path.join(LOG_DIR, f"session_{session_id}.jsonl")

    def _append_log(self, session_id: str, record: Dict[str, Any]) -> None:
        try:
            path = self._session_log_path(session_id)
            enriched = dict(record)
            enriched.setdefault("ts", datetime.now(timezone.utc).isoformat())
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("session_log_write_failed")

    def _load_prompt_template(self, difficulty: str) -> str:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
        path = os.path.join(base_dir, f"hp_quiz_{difficulty}.txt")
        if not os.path.exists(path):
            path = os.path.join(base_dir, "hp_quiz_base.txt")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _build_prompt(self, difficulty: str, history: List[bool], target: str, asked_texts: List[str], correct_examples: List[str], wrong_examples: List[str], user_filters: Dict[str, Any] | None) -> str:
        template = self._load_prompt_template(difficulty)
        return self.prompt_builder.build(
            template,
            difficulty=difficulty,
            target=target,
            asked_texts=asked_texts,
            correct_texts=correct_examples,
            wrong_texts=wrong_examples,
            user_filters=user_filters,
            question_count=settings.question_batch_size,
        )

    def _strip_code_fences(self, text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            parts = t.split("\n", 1)
            if len(parts) == 2:
                t = parts[1]
            if t.endswith("```"):
                t = t[:-3]
        if t.startswith("json\n"):
            t = t[5:]
        return t.strip()

    def _coerce_payload_to_list(self, obj: Any) -> List[Dict[str, Any]]:
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            if "questions" in obj and isinstance(obj["questions"], list):
                return obj["questions"]
        return []

    def _try_slice_to_array(self, text: str) -> List[Dict[str, Any]]:
        try:
            first = text.find("[")
            last = text.rfind("]")
            if first != -1 and last != -1 and last > first:
                return json.loads(text[first:last+1])
        except Exception:
            pass
        try:
            q_idx = text.find("\"questions\"")
            if q_idx != -1:
                sub = text[q_idx:]
                first = sub.find("[")
                last = sub.rfind("]")
                if first != -1 and last != -1 and last > first:
                    return json.loads(sub[first:last+1])
        except Exception:
            pass
        return []

    def _count_tokens(self, text: str) -> int | None:
        if not self.model_for_tokens:
            return None
        try:
            info = self.model_for_tokens.count_tokens(text)
            return getattr(info, "total_tokens", None) or getattr(info, "tokens", None)
        except Exception:
            return None

    def _parse_options(self, opts_raw: Any) -> List[Option]:
        opts: List[Option] = []
        if isinstance(opts_raw, list):
            if all(isinstance(o, dict) for o in opts_raw):
                for o in opts_raw:
                    opts.append(Option(id=o.get("id") or str(uuid.uuid4()), text=o.get("text", "")))
            elif all(isinstance(o, str) for o in opts_raw):
                for text in opts_raw:
                    opts.append(Option(id=str(uuid.uuid4()), text=text))
        return opts

    def _shuffle_options(self, options: List[Option], correct_option_id: str) -> tuple[List[Option], str]:
        """Shuffle options while tracking the new position of the correct answer"""
        # Create a copy to avoid modifying the original
        shuffled = options.copy()
        random.shuffle(shuffled)
        
        # Find the new ID of the correct option
        correct_option = next((opt for opt in options if opt.id == correct_option_id), None)
        if correct_option:
            new_correct_id = next((opt.id for opt in shuffled if opt.text == correct_option.text), correct_option_id)
        else:
            new_correct_id = correct_option_id
            
        return shuffled, new_correct_id

    def _norm_text(self, text: str) -> str:
        return (text or "").strip().lower()

    def log_user_answer(self, session_id: str, question_text: str | None, selected_text: str | None, correct_text: str | None, is_correct: bool) -> None:
        self._append_log(session_id, {"event": "answer", "question": question_text, "selected": selected_text, "correct_text": correct_text, "is_correct": is_correct})

    def generate_questions(self, difficulty: str, history: List[bool], target: str, count: int = 10, asked_texts: List[str] | None = None, correct_examples: List[str] | None = None, wrong_examples: List[str] | None = None, user_filters: Dict[str, Any] | None = None, session_id: str | None = None) -> List[Question]:
        if not settings.gemini_api_key:
            logger.warning({"event": "gemini_no_api_key", "message": "Using fallback questions"})
            return self._fallback_questions(difficulty, count)
        prompt = self._build_prompt(difficulty, history, target, asked_texts or [], correct_examples or [], wrong_examples or [], user_filters)
        input_tokens = self._count_tokens(prompt)
        if session_id:
            self._append_log(session_id, {"event": "prompt", "difficulty": difficulty, "target": target, "input_tokens": input_tokens, "prompt": prompt})
        try:
            logger.debug({"event": "gemini_request", "model": self.model_name, "input_tokens": input_tokens})
            model = genai.GenerativeModel(self.model_name, generation_config=self.generation_config)
            t0 = perf_counter()
            response = model.generate_content(prompt)
            latency_ms = int((perf_counter() - t0) * 1000)
            raw_text = (response.text or "").strip()
            output_tokens = None
            try:
                if hasattr(response, "usage_metadata"):
                    output_tokens = getattr(response.usage_metadata, "candidates_token_count", None)
            except Exception:
                output_tokens = None
            if not raw_text and getattr(response, "candidates", None):
                try:
                    parts = response.candidates[0].content.parts
                    raw_text = "".join(getattr(p, "text", "") for p in parts)
                except Exception:
                    raw_text = ""
            cleaned = self._strip_code_fences(raw_text)
            logger.debug({"event": "gemini_response", "preview": cleaned[:200], "latency_ms": latency_ms, "output_tokens": output_tokens})
            payload_obj = None
            try:
                payload_obj = json.loads(cleaned)
            except Exception:
                sliced = self._try_slice_to_array(cleaned)
                if sliced:
                    payload_obj = sliced
            if payload_obj is None:
                raise ValueError("payload_unparseable")
            payload = self._coerce_payload_to_list(payload_obj)
            if not payload:
                raise ValueError("payload_not_list")
            questions: List[Question] = []
            seen_norm_texts: set[str] = set()
            asked_norms: set[str] = set(self._norm_text(t) for t in (asked_texts or []))
            for item in payload[:count]:
                if not isinstance(item, dict):
                    continue
                qid = item.get("id") or str(uuid.uuid4())
                opts = self._parse_options(item.get("options", []))
                if not opts:
                    continue
                correct_id = None
                if "correct_option_id" in item and item.get("correct_option_id"):
                    correct_id = item.get("correct_option_id")
                elif isinstance(item.get("correct_index"), int):
                    idx = item.get("correct_index")
                    if 0 <= idx < len(opts):
                        correct_id = opts[idx].id
                if not correct_id:
                    correct_id = opts[0].id
                text_val = item.get("text", "")
                norm_text = self._norm_text(text_val)
                if norm_text in asked_norms:
                    continue
                if norm_text in seen_norm_texts:
                    continue
                seen_norm_texts.add(norm_text)
                
                # Shuffle options to prevent correct answers always being in position A
                shuffled_opts, shuffled_correct_id = self._shuffle_options(opts, correct_id)
                
                q = Question(id=qid, text=text_val, options=shuffled_opts, correct_option_id=shuffled_correct_id, difficulty=item.get("difficulty", difficulty))
                questions.append(q)
            if session_id:
                self._append_log(session_id, {"event": "generated", "difficulty": difficulty, "target": target, "count": len(questions), "latency_ms": latency_ms, "output_tokens": output_tokens})
            if not questions:
                logger.warning({"event": "gemini_empty_questions", "reason": "parsed_empty"})
                return self._fallback_questions(difficulty, count)
            return questions
        except Exception:
            logger.exception("gemini_parse_or_call_failed")
            return self._fallback_questions(difficulty, count)

    def _fallback_questions(self, difficulty: str, count: int) -> List[Question]:
        items: List[Question] = []
        for _ in range(count):
            qid = str(uuid.uuid4())
            opts = [
                Option(id=str(uuid.uuid4()), text="Harry"),
                Option(id=str(uuid.uuid4()), text="Ron"),
                Option(id=str(uuid.uuid4()), text="Hermione"),
                Option(id=str(uuid.uuid4()), text="Draco"),
            ]
            # Shuffle options for fallback questions too
            shuffled_opts, shuffled_correct_id = self._shuffle_options(opts, opts[0].id)
            items.append(Question(id=qid, text="Who is the boy who lived?", options=shuffled_opts, correct_option_id=shuffled_correct_id, difficulty=difficulty))
        logger.debug({"event": "fallback_questions_generated", "count": len(items), "difficulty": difficulty})
        return items
