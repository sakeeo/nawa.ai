from dataclasses import dataclass, replace

from nawa.knowledge.chunking import estimate_tokens
from nawa.knowledge.retrieval import Candidate

ELLIPSIS = " […dipotong]"


@dataclass(frozen=True)
class ContextPassage:
    marker: int
    candidate: Candidate


def _truncate(text: str, max_tokens: int) -> str:
    budget = max(max_tokens * 4 - len(ELLIPSIS), 1)
    return text[:budget].rstrip() + ELLIPSIS


def assemble_context(
    candidates: list[Candidate], *, max_tokens: int, final_k: int
) -> list[ContextPassage]:
    """Numbered passages in candidate order within a token budget. Chunks are never split.

    The first candidate is always kept (truncated with an explicit marker if it alone exceeds
    the budget). Exact duplicate texts are dropped.
    """
    passages: list[ContextPassage] = []
    seen: set[str] = set()
    used = 0
    for candidate in candidates:
        if len(passages) >= final_k:
            break
        if candidate.text in seen:
            continue
        cost = estimate_tokens(candidate.text)
        if not passages and cost > max_tokens:
            candidate = replace(candidate, text=_truncate(candidate.text, max_tokens))
            cost = estimate_tokens(candidate.text)
        elif used + cost > max_tokens:
            break
        seen.add(candidate.text)
        used += cost
        passages.append(ContextPassage(len(passages) + 1, candidate))
    return passages
