from dataclasses import dataclass
from typing import Literal

from nawa.knowledge.retrieval import Candidate


@dataclass(frozen=True)
class GateDecision:
    answerable: bool
    reason: Literal["ok", "no_candidates", "below_threshold"]
    best_similarity: float | None


def relevance_gate(candidates: list[Candidate], *, min_similarity: float) -> GateDecision:
    """Answerable only if the best cosine similarity among the candidates reaches the threshold."""
    if not candidates:
        return GateDecision(False, "no_candidates", None)
    best = max(c.similarity for c in candidates)
    if best >= min_similarity:
        return GateDecision(True, "ok", best)
    return GateDecision(False, "below_threshold", best)
