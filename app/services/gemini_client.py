import os
import json
import uuid
from typing import List, Dict, Any
import logging
import google.generativeai as genai
from ..config import settings
from ..models import Question, Option

logger = logging.getLogger("adaptive_hp_quiz")

class GeminiQuestionGenerator:
    def __init__(self) -> None:
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model
        self.generation_config = {
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 40,
            "response_mime_type": "application/json",
        }

    def _load_prompt_template(self, difficulty: str) -> str:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
        path = os.path.join(base_dir, f"hp_quiz_{difficulty}.txt")
        if not os.path.exists(path):
            path = os.path.join(base_dir, "hp_quiz_base.txt")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _build_prompt(self, difficulty: str, history: List[bool], target: str, asked_texts: List[str], correct_examples: List[str], wrong_examples: List[str], user_filters: Dict[str, Any] | None) -> str:
        template = self._load_prompt_template(difficulty)
        instructions = {
            "history": history,
            "target": target,
            "domain": "Harry Potter trivia",
            "avoid_repeat_questions_texts": asked_texts,
            "correct_examples": correct_examples,
            "wrong_examples": wrong_examples,
            "user_filters": user_filters or {},
            "format": {
                "num_questions": settings.question_batch_size,
                "question_shape": {
                    "id": "string",
                    "text": "string",
                    "options": [{"id": "string", "text": "string"}],
                    "correct_option_id": "string",
                    "difficulty": "easy|medium|hard"
                }
            }
        }
        return template + "\n" + json.dumps(instructions)

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

    def generate_questions(self, difficulty: str, history: List[bool], target: str, count: int = 10, asked_texts: List[str] | None = None, correct_examples: List[str] | None = None, wrong_examples: List[str] | None = None, user_filters: Dict[str, Any] | None = None) -> List[Question]:
        if not settings.gemini_api_key:
            logger.warning({"event": "gemini_no_api_key", "message": "Using fallback questions"})
            return self._fallback_questions(difficulty, count)
        prompt = self._build_prompt(difficulty, history, target, asked_texts or [], correct_examples or [], wrong_examples or [], user_filters)
        try:
            logger.debug({"event": "gemini_request", "model": self.model_name, "prompt_bytes": len(prompt)})
            model = genai.GenerativeModel(self.model_name, generation_config=self.generation_config)
            response = model.generate_content(prompt)
            raw_text = (response.text or "").strip()
            if not raw_text and getattr(response, "candidates", None):
                try:
                    parts = response.candidates[0].content.parts
                    raw_text = "".join(getattr(p, "text", "") for p in parts)
                except Exception:
                    raw_text = ""
            cleaned = self._strip_code_fences(raw_text)
            logger.debug({"event": "gemini_response", "preview": cleaned[:200]})
            payload_obj = json.loads(cleaned)
            payload = self._coerce_payload_to_list(payload_obj)
            if not payload:
                raise ValueError("payload_not_list")
            questions: List[Question] = []
            for item in payload[:count]:
                if not isinstance(item, dict):
                    continue
                qid = item.get("id") or str(uuid.uuid4())
                opts_raw = item.get("options", [])
                opts: List[Option] = []
                for o in opts_raw:
                    if isinstance(o, dict):
                        opts.append(Option(id=o.get("id") or str(uuid.uuid4()), text=o.get("text", "")))
                if not opts:
                    continue
                correct_id = item.get("correct_option_id") or opts[0].id
                text_val = item.get("text", "")
                q = Question(id=qid, text=text_val, options=opts, correct_option_id=correct_id, difficulty=item.get("difficulty", difficulty))
                if asked_texts and text_val in asked_texts:
                    continue
                questions.append(q)
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
            items.append(Question(id=qid, text="Who is the boy who lived?", options=opts, correct_option_id=opts[0].id, difficulty=difficulty))
        logger.debug({"event": "fallback_questions_generated", "count": len(items), "difficulty": difficulty})
        return items
