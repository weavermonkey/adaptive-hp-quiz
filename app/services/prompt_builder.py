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
			"Do NOT ask any question that appears in already_asked_questions (no rewording or paraphrasing). "
			"Raise difficulty if meta.target is harder; lower if easier; otherwise baseline. "
			"Prefer topics from correct_questions and avoid topics from wrong_questions. "
			"Return only the required JSON schema."
		)
		return template_text + "\n" + instructions + "\n" + json.dumps(context)
