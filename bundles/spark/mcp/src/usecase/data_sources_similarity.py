"""Vendor-name similarity check.

When an operator uploads a custom data_source.yaml, the `vendor:` field
might be a misspelling of an existing canonical vendor name (e.g.
"AcmeCrop" → "AcmeCorp"). This module:

  1. Computes a normalized similarity between the uploaded vendor and
     every known canonical vendor.
  2. Returns the top-k matches above a threshold, so the upload-preview
     endpoint can show "did you mean Amazon?" prompts.
  3. Lets the operator decide at commit time:
       • create_new   — keep the vendor as-typed (new vendor group)
       • group_under  — replace the YAML's vendor with the canonical name

# Strategy

Two matchers run in parallel and the union is returned:

  • **Levenshtein** distance with threshold ≤ 2 (per the brainstorm
    decision). Catches typos like "AcmeCrop" → "AcmeCorp" (edit_dist=1)
    and "Fortinte" → "Fortinet" (edit_dist=2). Case-insensitive.

  • **Substring**. Either side a substring of the other. Catches partial
    names like "Acme" → "AcmeCorp" or "Fortinet FortiGate" → "Fortinet".
    Case-insensitive.

The two matchers can both fire for the same candidate; we de-duplicate by
vendor name and keep the strongest signal (Levenshtein < substring).

# Why not difflib.get_close_matches

`difflib.SequenceMatcher` uses ratio scoring which is sensitive to length;
short typos against long vendor names score poorly. Direct Levenshtein
captures the operator's intuition (1-character typo = obvious match)
without false negatives on length asymmetry. We implement it inline (10
lines) rather than pulling python-Levenshtein, which is a compiled
extension we'd rather avoid in the image.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# ─── Public types ──────────────────────────────────────────────────


@dataclass
class SimilarityMatch:
    """One candidate vendor that's similar to the uploaded vendor name."""

    vendor: str           # Canonical vendor name (matches an existing entry)
    similarity: str       # "levenshtein" | "substring" | "exact"
    distance: int | None  # Edit distance for levenshtein; None for substring/exact

    def to_dict(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "similarity": self.similarity,
            "distance": self.distance,
        }


# ─── Match ranking ─────────────────────────────────────────────────


_LEVENSHTEIN_THRESHOLD = 2


def find_similar_vendors(
    uploaded_vendor: str,
    known_vendors: Iterable[str],
    *,
    top_k: int = 5,
) -> list[SimilarityMatch]:
    """Return up to `top_k` known vendors similar to `uploaded_vendor`.

    The list is sorted strongest-match first:
      1. Exact match (case-insensitive)
      2. Lowest Levenshtein distance (1 before 2)
      3. Substring matches (alphabetical to break ties)

    Empty inputs return an empty list. The uploaded vendor itself is
    excluded from the result (even on case-insensitive exact match) —
    callers want "did you mean X?" suggestions, not "you typed X".

    A caller using this for the upload-preview endpoint should:
      • If exact match present → still suggest (operator decides whether
        to group under the canonical name, which may differ only by case).
      • If no matches → no prompt; commit goes straight through.
    """
    uv = (uploaded_vendor or "").strip()
    if not uv:
        return []
    uv_lower = uv.lower()

    candidates: dict[str, SimilarityMatch] = {}

    for known in known_vendors:
        if not known:
            continue
        known_lower = known.lower()
        # Skip self-match (case-insensitive)
        if known_lower == uv_lower and known == uv:
            continue

        # Exact match (case-different)
        if known_lower == uv_lower:
            candidates[known] = SimilarityMatch(
                vendor=known, similarity="exact", distance=0,
            )
            continue

        # Levenshtein
        d = _levenshtein(uv_lower, known_lower)
        if d <= _LEVENSHTEIN_THRESHOLD:
            existing = candidates.get(known)
            if existing is None or (
                existing.similarity == "substring" or (existing.distance or 99) > d
            ):
                candidates[known] = SimilarityMatch(
                    vendor=known, similarity="levenshtein", distance=d,
                )
            continue

        # Substring (either direction). Skip very-short uploaded vendors
        # to avoid noise — single-letter substrings match dozens of names.
        if len(uv_lower) >= 3 and (uv_lower in known_lower or known_lower in uv_lower):
            if known not in candidates:
                candidates[known] = SimilarityMatch(
                    vendor=known, similarity="substring", distance=None,
                )

    # Rank: exact (distance=0) < levenshtein 1 < levenshtein 2 < substring (no distance)
    def _sort_key(m: SimilarityMatch) -> tuple[int, int, str]:
        if m.similarity == "exact":
            return (0, 0, m.vendor.lower())
        if m.similarity == "levenshtein":
            return (1, m.distance or 99, m.vendor.lower())
        return (2, 99, m.vendor.lower())  # substring

    ranked = sorted(candidates.values(), key=_sort_key)
    return ranked[:top_k]


# ─── Levenshtein implementation ────────────────────────────────────


def _levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein edit distance between two strings.

    Standard DP — O(len(a) * len(b)) time, O(min(len(a), len(b))) space.
    Returns an int >= 0; 0 means identical.

    For Phantom's use (vendor name comparison, both strings short), this
    is plenty fast: ~150 known vendors × <30 chars each = <5ms total
    per upload-preview call.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Always iterate the shorter string in the inner loop
    if len(a) < len(b):
        a, b = b, a

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,        # insertion
                prev[j] + 1,            # deletion
                prev[j - 1] + cost,     # substitution
            )
        prev = curr
    return prev[-1]
