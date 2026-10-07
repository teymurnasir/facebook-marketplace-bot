"""Extract seller statements about Ontario safety certification."""

from __future__ import annotations

import re


NEGATIVE = re.compile(
    r"\b(?:no|without)\s+(?:a\s+)?(?:valid\s+|current\s+)?safety\b"
    r"|\bnot\s+(?:safetied|safety\s+certified|certified)\b"
    r"|\b(?:needs?|requires?)\s+(?:a\s+)?safety\b"
    r"|\bsafety\s*(?::|is)?\s*(?:no|not\s+included|expired)\b"
    r"|\b(?:sold|selling|sell)\s+as[ -]is\b|\bas[ -]is\b"
    r"|\b(?:won't|will\s+not|cannot|can't|does\s+not|doesn't|failed\s+to)\s+pass\s+(?:a\s+)?safety\b",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(
    r"\b(?:can|could|will|would|should|may|might)\b.{0,40}\b(?:safety|safetied|certified)\b"
    r"|\bsafety\b.{0,40}\b(?:extra|additional|available|optional|cost|fee|\$|expired)\b"
    r"|\b(?:certified|safetied)\b.{0,30}\b(?:extra|additional|available|optional|upon|on\s+request)\b"
    r"|\b(?:was|previously)\s+(?:safetied|certified)\b",
    re.IGNORECASE,
)
POSITIVE = re.compile(
    r"\bsafety\s*(?::|is)?\s*(?:yes|included|done|passed|completed|certified)\b"
    r"|\b(?:with|includes?|including|comes\s+with)\s+(?:a\s+)?(?:valid\s+|current\s+)?safety(?:\s+(?:standards?\s+)?certificate)?\b"
    r"|\b(?:passed|completed)\s+(?:the\s+|a\s+)?safety\b"
    r"|\b(?:freshly|recently|newly)\s+(?:safetied|safety\s+certified)\b"
    r"|\bsafetied\b|\bsafety\s+(?:standards?\s+)?certificate\s+(?:included|provided|valid)\b",
    re.IGNORECASE,
)


def classify_safety(description: str) -> tuple[str, str]:
    """Return yes/no/unknown and a short seller excerpt, never a safety guarantee."""
    statements = [s.strip() for s in re.split(r"[\n.!?;]+", description or "") if s.strip()]
    positive = []
    negative = []
    conditional = []
    for statement in statements:
        if NEGATIVE.search(statement):
            negative.append(statement)
        elif CONDITIONAL.search(statement):
            conditional.append(statement)
        elif POSITIVE.search(statement):
            positive.append(statement)
    if negative and positive:
        return "unknown", (negative[0] + "; " + positive[0])[:160]
    if negative:
        return "no", negative[0][:160]
    if conditional:
        return "unknown", conditional[0][:160]
    if positive:
        return "yes", positive[0][:160]
    return "unknown", ""
