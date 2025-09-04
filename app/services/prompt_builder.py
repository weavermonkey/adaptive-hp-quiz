import json
from typing import List, Dict, Any

class PromptBuilder:
	def build(self, template_text: str, *, difficulty: str, target: str, asked_texts: List[str], correct_texts: List[str], wrong_texts: List[str], user_filters: Dict[str, Any] | None, question_count: int) -> str:
		context = {
			"meta": {"difficulty": difficulty, "target": target},
			"already_asked_questions": asked_texts,
			"correct_questions": correct_texts,
			"wrong_questions": wrong_texts,
			"user_filters": user_filters or {},
			"format": {
				"num_questions": question_count,
				"question_shape": {
					"id": "string",
					"text": "string",
					"options": [{"id": "string", "text": "string"}],
					"correct_option_id": "string",
					"difficulty": "easy|medium|hard"
				}
			}
		}
		instructions = (
			"Use the CONTEXT JSON below to guide generation. "
			"You are a generator of multiple-choice Harry Potter questions. Output must be strict JSON only. "
			"Content rule: Use ONLY the seven books (no movies or extra-canonical sources). "
			"Here are lists: already_asked_questions, correct_questions, wrong_questions. "
			"Based on this information, generate new, unseen questions at the requested difficulty (meta.target: harder/easier/baseline), never repeating any text from already_asked_questions (no paraphrases). "
			"Return only the required JSON schema."
		)
		return template_text + "\n" + instructions + "\n" + json.dumps(context)
