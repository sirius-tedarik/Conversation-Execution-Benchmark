"""Deterministic simulation of Turkish speech-to-text errors on the caller's side.

Every case in this suite hands the model a clean, well-typed sentence. A real caller is
transcribed first, and the transcript is where a phone agent's input actually comes from:
fillers survive, word-final syllables are eaten, long digit runs get re-spaced, the question
particle gets glued to or split from its host word, and the first phoneme of a turn is clipped
because the recogniser opened late. None of that was represented anywhere.

The point of this module is NOT to see whether the model can undo a transcription error — most
of the time it cannot, and a benchmark that demanded telepathy would be measuring luck. It is to
put the suite's existing expectations under realistic input noise and see which ones survive.
A case that passes clean and fails under `light` noise is a case whose behaviour depended on the
caller's punctuation.

One operator is different in kind and is deliberately quarantined. `drop_negation` turns
"istemiyorum" into "istiyorum" — it inverts the caller's meaning, and no agent can recover the
original from the text alone. It never appears in the graded profiles. It exists for cases that
are built around it, where the corrupted turn CONTRADICTS something the caller established
earlier and the correct behaviour is to notice the conflict and re-confirm rather than act.

Determinism: every decision is a hash of (seed, scenario_id, node_id, visit, operator), so a run
replays identically and a failure can be reproduced from the seed alone.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

FILLERS = ("ıı", "şey", "yani", "hı hı", "ee")

# Colloquial reductions a Turkish recogniser reproduces from casual speech rather than "fixing".
_ELISIONS = (
    (re.compile(r"acağım\b"), "acam"),
    (re.compile(r"eceğim\b"), "ecem"),
    (re.compile(r"acağız\b"), "acaz"),
    (re.compile(r"eceğiz\b"), "ecez"),
    (re.compile(r"[ıi]yorum\b"), "yom"),
    (re.compile(r"muşum\b"), "mişim"),
)

# Spoken number words that sit one phoneme apart. A recogniser picks the wrong one under noise,
# and the two members of each pair mean very different things once they reach a tool argument.
_NUMBER_CONFUSIONS = (
    ("dört", "dert"),
    ("sekiz", "seksen"),
    ("bir", "bin"),
    ("yedi", "yedek"),
    ("altı", "alt"),
    ("iki", "ikiz"),
    ("otuz", "on üç"),
)

# The question particle is written apart from its host in Turkish, which is exactly the boundary
# a recogniser gets wrong in both directions: "kartımı" heard as "kartı mı" flips a statement
# into a question about a different object.
_BOUNDARY = re.compile(r"\b(\w{3,})(m[ıiuü])\b")

_DIGIT_RUN = re.compile(r"\b(\d{7,})\b")

CROSSTALK = (
    "arkadan bir ses geliyor",
    "bir saniye",
    "kim o",
    "dur dur",
)

# A recogniser that eats the negation suffix still emits a REAL word, so the common imperatives
# are listed explicitly and the generic suffix rule only catches what is left.
_NEGATIONS = (
    (re.compile(r"\biste(m[ıi]yorum|mem)\b"), "istiyorum"),
    (re.compile(r"\betmeyin\b"), "edin"),
    (re.compile(r"\bkapatmayın\b"), "kapatın"),
    (re.compile(r"\bvermeyin\b"), "verin"),
    (re.compile(r"\bsöylemeyin\b"), "söyleyin"),
    (re.compile(r"\byapmayın\b"), "yapın"),
    (re.compile(r"\bgöndermeyin\b"), "gönderin"),
    (re.compile(r"\b(\w+)me(y[ıi]n)\b"), r"\1in"),
    (re.compile(r"\b(\w+)ma(y[ıi]n)\b"), r"\1ın"),
    (re.compile(r"\bdeğil\b"), ""),
    (re.compile(r"\byok\b"), "var"),
)

#: name -> per-turn probability. Ordered from harmless to meaning-bearing; `drop_negation` is
#: absent from every graded profile on purpose (see the module docstring).
PROFILES: dict[str, dict[str, float]] = {
    "light": {"filler": 0.30, "elide_final": 0.30, "drop_punct": 0.50, "stutter": 0.15},
    "moderate": {
        "filler": 0.45, "elide_final": 0.45, "drop_punct": 0.70, "stutter": 0.25,
        "split_digits": 0.50, "boundary_shift": 0.30, "clip_onset": 0.20, "crosstalk": 0.20,
    },
    "heavy": {
        "filler": 0.60, "elide_final": 0.55, "drop_punct": 0.90, "stutter": 0.35,
        "split_digits": 0.70, "boundary_shift": 0.45, "clip_onset": 0.35, "crosstalk": 0.35,
        "number_homophone": 0.35,
    },
    # For cases built around a meaning-inverting mis-transcription. Never use it to grade a case
    # that simply expects the caller's negation to be honoured — the model cannot see the loss.
    "meaning_inverting": {"drop_negation": 1.0},
}


def _roll(seed: int, scenario_id: str, node_id: str, visit: int, operator: str) -> float:
    digest = hashlib.sha256(f"stt:{seed}:{scenario_id}:{node_id}:{visit}:{operator}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _pick(options: tuple[str, ...], seed: int, scenario_id: str, node_id: str, visit: int, operator: str) -> str:
    digest = hashlib.sha256(f"pick:{seed}:{scenario_id}:{node_id}:{visit}:{operator}".encode()).digest()
    return options[int.from_bytes(digest[:8], "big") % len(options)]


def _apply_filler(text: str, ctx: tuple) -> str:
    filler = _pick(FILLERS, *ctx, "filler")
    words = text.split(" ")
    if len(words) < 2:
        return f"{filler} {text}"
    position = 1 + int(_roll(*ctx, "filler_pos") * (len(words) - 1))
    return " ".join(words[:position] + [filler] + words[position:])


def _apply_elide_final(text: str, ctx: tuple) -> str:
    for pattern, replacement in _ELISIONS:
        if pattern.search(text):
            return pattern.sub(replacement, text, count=1)
    return text


def _apply_drop_punct(text: str, ctx: tuple) -> str:
    return text.replace("?", "").replace(",", "").replace(";", "").rstrip()


def _apply_stutter(text: str, ctx: tuple) -> str:
    words = text.split(" ")
    if not words or not words[0]:
        return text
    return " ".join([words[0].lower(), *words])


def _apply_clip_onset(text: str, ctx: tuple) -> str:
    if len(text) < 4:
        return text
    return text[1:]


def _apply_split_digits(text: str, ctx: tuple) -> str:
    def split(match: re.Match[str]) -> str:
        digits = match.group(1)
        cut = 1 + int(_roll(*ctx, "digit_cut") * (len(digits) - 2))
        return f"{digits[:cut]} {digits[cut:]}"

    return _DIGIT_RUN.sub(split, text, count=1)


def _apply_boundary_shift(text: str, ctx: tuple) -> str:
    return _BOUNDARY.sub(r"\1 \2", text, count=1)


def _apply_crosstalk(text: str, ctx: tuple) -> str:
    return f"{text} {_pick(CROSSTALK, *ctx, 'crosstalk')}"


def _apply_number_homophone(text: str, ctx: tuple) -> str:
    for left, right in _NUMBER_CONFUSIONS:
        pattern = re.compile(rf"\b{left}\b")
        if pattern.search(text):
            return pattern.sub(right, text, count=1)
    return text


def _apply_drop_negation(text: str, ctx: tuple) -> str:
    for pattern, replacement in _NEGATIONS:
        if pattern.search(text):
            return re.sub(r"\s{2,}", " ", pattern.sub(replacement, text, count=1)).strip()
    return text


_OPERATORS = {
    "filler": _apply_filler,
    "elide_final": _apply_elide_final,
    "drop_punct": _apply_drop_punct,
    "stutter": _apply_stutter,
    "clip_onset": _apply_clip_onset,
    "split_digits": _apply_split_digits,
    "boundary_shift": _apply_boundary_shift,
    "crosstalk": _apply_crosstalk,
    "number_homophone": _apply_number_homophone,
    "drop_negation": _apply_drop_negation,
}

#: Operators listed here change what the caller asked for. Reported separately so a sweep can
#: say how much of its damage came from noise the agent could not have seen through.
MEANING_BEARING = frozenset({"number_homophone", "drop_negation"})


def resolve_profile(profile: str | dict[str, float] | None) -> dict[str, float]:
    """A profile name, an explicit operator->rate mapping, or nothing at all."""
    if not profile:
        return {}
    if isinstance(profile, dict):
        unknown = set(profile) - set(_OPERATORS)
        if unknown:
            raise ValueError(f"unknown stt operators: {sorted(unknown)}")
        return profile
    if profile not in PROFILES:
        raise ValueError(f"unknown stt profile: {profile}; known: {sorted(PROFILES)}")
    return PROFILES[profile]


def transcribe(
    utterance: str,
    profile: str | dict[str, float] | None,
    seed: int,
    scenario_id: str,
    node_id: str,
    visit: int,
) -> tuple[str, list[str]]:
    """Return the utterance as a recogniser would have produced it, plus the operators applied.

    An operator that finds nothing to change leaves the text alone and is not reported, so the
    applied list names real edits rather than attempted ones.
    """
    rates = resolve_profile(profile)
    if not rates:
        return utterance, []
    ctx = (seed, scenario_id, node_id, visit)
    text = utterance
    applied: list[str] = []
    for name in _OPERATORS:
        rate = rates.get(name, 0.0)
        if rate <= 0.0 or _roll(*ctx, name) >= rate:
            continue
        candidate = _OPERATORS[name](text, ctx)
        if candidate != text:
            text = candidate
            applied.append(name)
    return text, applied


def summarise(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate what the recogniser actually did across a run, for the report."""
    counts: dict[str, int] = {}
    turns_altered = 0
    meaning_bearing_turns = 0
    for entry in trace:
        applied = entry.get("stt_applied") or []
        if applied:
            turns_altered += 1
        if any(name in MEANING_BEARING for name in applied):
            meaning_bearing_turns += 1
        for name in applied:
            counts[name] = counts.get(name, 0) + 1
    return {
        "turns_altered": turns_altered,
        "meaning_bearing_turns": meaning_bearing_turns,
        "operator_counts": counts,
    }
