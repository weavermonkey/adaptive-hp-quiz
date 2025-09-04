from typing import List

def determine_next_difficulty(recent_results: List[bool]) -> str:
    correct = sum(1 for r in recent_results if r)
    total = len(recent_results)
    if total == 0:
        return "none"
    if correct >= total - 1:
        return "increase"
    if correct <= 1:
        return "decrease"
    return "none"
