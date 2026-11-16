"""Versioned Case06 v5.1 report-claim guard; science calculations are unchanged."""
from __future__ import annotations

import re

VERSION = "case06-v5.1-report-claims/v1"

_TARGET = re.compile(r"\b(?:minimum|minima|stationarity|stationary|curvature)\b", re.I)
_CLAIM_VERB = re.compile(
    r"\b(?:pass(?:ed)?|certif\w*|prov\w*|establish\w*|demonstrat\w*|"
    r"claim\w*|assert\w*|confirm\w*|verif\w*|show\w*|find\w*|"
    r"achiev\w*|satisf\w*|found)\b",
    re.I,
)
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|isn't|aren't|doesn't|don't|"
    r"wasn't|weren't|hasn't|haven't|hadn't|unverified|unsupported)\b",
    re.I,
)
_DIRECT_CURVATURE_POSITIVE = re.compile(
    r"\b(?:curvature\s+(?:is|was|remains|became|appears|has)\s+"
    r"(?:strictly\s+)?positive|(?:a\s+)?positive\s+curvature\s+was\s+found)\b",
    re.I,
)


def _clauses(text: str) -> list[str]:
    # Sentence and semicolon boundaries plus explicit contrast keep a denial
    # from cancelling an independent positive assertion in the next clause.
    return [part.strip() for part in re.split(
        r"(?<=[.!?])\s+|\r?\n+|;\s*|,\s*(?=(?:minimum|minima|stationarity|stationary|curvature)\b)|"
        r"\b(?:but|however|yet)\b|"
        r"\band\s+(?=(?:a|an|the|minimum|minima|stationarity|stationary|curvature|"
        r"positive\s+curvature|we|it|this|that)\b)",
        text,
        flags=re.I,
    ) if part.strip()]


def _negates_relation(clause: str, target_start: int, event_start: int, event_end: int) -> bool:
    # Parenthetical asides cannot negate a claim outside their own scope (for
    # example, “Minimum (not Hessian): PASS”).
    scoped = re.sub(r"\([^)]*\)", lambda m: " " * len(m.group(0)), clause)
    left = min(target_start, event_start)
    relation = scoped[left:event_end]
    # A preceding "No" can govern the target ("No minimum is certified").
    prefix = scoped[max(0, target_start - 22):target_start]
    candidates = list(_NEGATION.finditer(prefix + relation))
    for match in candidates:
        after = (prefix + relation)[match.end():]
        word = match.group(0).lower()
        if word == "not" and re.match(r"\s+(?:only|just|merely)\b", after, re.I):
            continue
        # Do not let an unrelated list item or adverb turn a true claim into a
        # denial: a scoped negation must occur between target and claim event,
        # or in the short prefix directly governing the target.
        if match.start() >= len(prefix) or (
            len(prefix) - match.start() <= 12
            and not re.search(r"[,;:/]", prefix[match.end():])
            and not _TARGET.search(prefix[match.end():])
        ):
            return True
    return False


def _has_unsupported_assertion(clause: str) -> bool:
    targets = list(_TARGET.finditer(clause))
    if not targets:
        return False

    events: list[tuple[int, int, int]] = []
    for target in targets:
        for verb in _CLAIM_VERB.finditer(clause):
            # A claim verb must be syntactically close to a minimum/curvature
            # term. Long-range cross-pairing across a sentence is disallowed.
            if target.end() <= verb.start():
                gap = clause[target.end():verb.start()]
                start, end = target.start(), verb.end()
            elif verb.end() <= target.start():
                gap = clause[verb.end():target.start()]
                start, end = verb.start(), target.end()
            else:
                gap = ""
                start, end = min(target.start(), verb.start()), max(target.end(), verb.end())
            if len(gap) <= 64 and not re.search(r"[,;.!?]", gap):
                events.append((target.start(), start, end))

        # Explicit status declarations are assertions only for positive values;
        # OUT_OF_SCOPE/UNVERIFIED are intentionally not claim events.
        status = re.search(
            rf"\b{target.group(0)}\b(?:[\w/ -]{{0,24}}?)\s*[:=]\s*"
            r"(?:PASS(?:ED)?|CERTIFIED|PROVEN|ESTABLISHED|POSITIVE)\b",
            clause[target.start():],
            re.I,
        )
        if status:
            events.append((target.start(), target.start(), target.start() + status.end()))

    # “Curvature is positive” is a direct assertion. The adjective in the noun
    # phrase “positive curvature” alone is not.
    for match in _DIRECT_CURVATURE_POSITIVE.finditer(clause):
        target = next((item for item in targets if match.start() <= item.start() < match.end()), None)
        if target is not None:
            events.append((target.start(), match.start(), match.end()))

    # A bare positive-curvature status is itself an assertion unless locally
    # negated or explicitly marked out of scope.
    for match in re.finditer(r"\bpositive\s+curvature\b", clause, re.I):
        target = next((item for item in targets if match.start() <= item.start() < match.end()), None)
        tail = clause[match.end():match.end() + 72]
        locally_denied = bool(_NEGATION.search(tail) and _CLAIM_VERB.search(tail))
        locally_out_of_scope = bool(re.match(
            r"\s*(?::\s*OUT_OF_SCOPE(?:_FOR_[A-Z0-9_]+)?\b|"
            r"(?:is|are)\s+outside\s+(?:(?:the|this)\s+)?(?:assessment|scope)\b)",
            tail,
            re.I,
        ))
        if target is not None and not locally_denied and not locally_out_of_scope:
            events.append((target.start(), match.start(), match.end()))

    for target_start, start, end in events:
        if not _negates_relation(clause, target_start, start, end):
            return True
    return False


def check_report_minimum_claims(report_text: str) -> None:
    """Reject positive minimum/stationarity/curvature claims, including mixed clauses."""
    for clause in _clauses(report_text):
        if _has_unsupported_assertion(clause):
            raise ValueError("Agent report makes an unsupported minimum/curvature PASS claim")

    # The legacy English rules above remain unchanged. Check Chinese clauses
    # independently so a denial in a later clause cannot cancel a positive
    # minimum or curvature assertion that appeared earlier.
    chinese_clauses = re.split(r"[,，;；。.!?！？\n]+|并且|且|而|与|但|然而|可是|不过", report_text)
    targets = ("最低点", "极小点", "驻点")
    confirmation = r"确认|验证|证明|证实|表明|发现|找到|确定|建立"
    negative = re.compile(r"不(?!仅|但)|未|无(?!疑)|没有|尚未|无法|不能|并未|未经|不曾")
    for clause in chinese_clauses:
        if negative.search(clause):
            continue
        for target in targets:
            claimed = (
                re.search(rf"(?:{confirmation}).{{0,16}}{target}", clause)
                or re.search(rf"{target}.{{0,12}}(?:已被)?(?:{confirmation})", clause)
                or re.search(rf"(?:为|是|均为|属于).{{0,6}}{target}", clause)
            )
            if claimed:
                raise ValueError("Agent report makes an unsupported minimum/stationarity claim")
        if re.search(r"曲率.{0,12}(?:为正|是正(?:值)?|呈正值|大于零)|正曲率", clause):
            raise ValueError("Agent report makes an unsupported positive-curvature claim")
