"""Answer extraction and scoring against dataset references."""
from __future__ import annotations

import re

ANSWER_TAG = re.compile(r"<answer>(.*?)</answer>", re.S | re.I)
FINAL_LINE = re.compile(r"(?:final answer|answer)\s*[:：]\s*(.+)", re.I)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")

SCORERS = {
    "auto": "Numeric if the reference is a number, otherwise exact or containment match",
    "exact": "Normalized exact match of the extracted answer",
    "contains": "Reference appears in the answer (case-insensitive)",
    "numeric": "Last number in the answer equals the reference within tolerance",
    "regex": "Reference is a regex that must match the answer",
    "llm_judge": "An LLM compares the answer with the reference",
    "none": "No scoring (measure cost/latency only)",
}

JUDGE_PROMPT = """You are grading an AI system's answer against a reference answer.

Task:
{task}

Reference answer:
{expected}

System answer:
{answer}

Is the system answer correct, i.e. semantically equivalent to the reference for the purposes of the task?
Reply with a short justification, then a final line that is exactly `VERDICT: CORRECT` or `VERDICT: INCORRECT`."""


def extract_answer(text: str | None) -> str:
    if not text:
        return ""
    tags = ANSWER_TAG.findall(text)
    if tags:
        return tags[-1].strip()
    lines = [l for l in text.strip().splitlines() if l.strip()]
    for line in reversed(lines[-5:]):
        m = FINAL_LINE.search(line)
        if m:
            return m.group(1).strip()
    return text.strip()


def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[*_`]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,;:!\"'")


def _to_number(s: str) -> float | None:
    nums = NUMBER.findall(s or "")
    if not nums:
        return None
    try:
        return float(nums[-1].replace(",", ""))
    except ValueError:
        return None


def _is_number(s: str) -> bool:
    return re.fullmatch(r"\s*-?\d[\d,]*(?:\.\d+)?\s*", s or "") is not None


def score_rule(scorer: dict, expected: str | None, answer: str | None) -> tuple[bool | None, str]:
    kind = scorer.get("type", "auto")
    if kind == "none" or expected is None or expected == "":
        return None, "not scored"
    extracted = extract_answer(answer)
    if kind == "auto":
        kind = "numeric" if _is_number(expected) else "exact_or_contains"
    if kind == "numeric":
        tol = float(scorer.get("tolerance") or 1e-6)
        a, b = _to_number(extracted), _to_number(expected)
        if a is None or b is None:
            return False, f"no number found (answer={extracted[:80]!r})"
        ok = abs(a - b) <= tol * max(1.0, abs(b))
        return ok, f"{a} vs {b}"
    if kind == "exact":
        return normalize(extracted) == normalize(expected), f"extracted={extracted[:120]!r}"
    if kind == "contains":
        return normalize(expected) in normalize(answer or ""), ""
    if kind == "exact_or_contains":
        ok = normalize(extracted) == normalize(expected) or normalize(expected) in normalize(extracted)
        return ok, f"extracted={extracted[:120]!r}"
    if kind == "regex":
        try:
            return re.search(expected, answer or "", re.S | re.I) is not None, ""
        except re.error as e:
            return False, f"bad regex: {e}"
    return None, f"unknown scorer {kind}"


def parse_judge(text: str) -> bool | None:
    m = re.findall(r"VERDICT:\s*(CORRECT|INCORRECT)", text or "", re.I)
    if not m:
        return None
    return m[-1].upper() == "CORRECT"
