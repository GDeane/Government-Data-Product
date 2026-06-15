"""Entity resolution — the hardest data problem and the showcase of the build (spec §2.2).

A false *merge* inflates apparent monopoly and suppresses real turnover; a false *split*
hides monopoly and fabricates phantom turnover. Both pillars of the score depend on getting
this right, so the design is deliberately conservative on merges (NFR4) and measurable
(D3.4).

Pipeline (D3.1): clean -> M&A crosswalk -> blocking -> rapidfuzz pairwise -> three-band
decision with a pluggable adjudicator -> needs_review for the unsure middle. The default
adjudicator is deterministic (rule-based) so the system runs with **no API key**; an LLM
adjudicator implements the same `Adjudicator` protocol and is dropped in only for the
ambiguous band (spec §2.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from rapidfuzz import fuzz

from .config import ER_CONFIG, EntityResolutionConfig

# --- Name cleaning --------------------------------------------------------------------
# Legal suffixes stripped before comparison (so "Acme Inc." == "Acme Ltd" on the stem).
_LEGAL_SUFFIXES = (
    "incorporated", "inc", "limited", "ltd", "ltee", "ltée", "llp", "llc", "lp",
    "corporation", "corp", "co", "company", "plc", "sarl", "sa", "gmbh", "pte",
    "enr", "enrg", "cie", "sencrl", "srl",
)
# Regional-office qualifiers stripped so "Deloitte Toronto" == "Deloitte Ottawa".
_REGIONAL_QUALIFIERS = (
    "toronto", "ottawa", "montreal", "vancouver", "calgary", "edmonton", "halifax",
    "winnipeg", "quebec", "gatineau", "canada", "national capital region", "ncr",
    "eastern", "western", "atlantic", "pacific", "central", "region", "office", "branch",
)
# Joiners / stopwords (EN + FR) dropped before comparison so "McKinsey & Company" and
# "McKinsey and Company" collapse to the same stem.
_STOPWORDS = ("and", "the", "of", "et", "de", "des", "du", "la", "le", "les", "aux", "a")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def clean_name(name) -> str:
    """Casefold, strip punctuation, drop legal suffixes and regional qualifiers, collapse
    whitespace. Returns the comparison stem. Empty input -> ''."""
    if name is None:
        return ""
    text = str(name).lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = _WS_RE.sub(" ", text).strip().split()
    tokens = [t for t in tokens if t not in _LEGAL_SUFFIXES
              and t not in _REGIONAL_QUALIFIERS and t not in _STOPWORDS]
    return " ".join(tokens)


# --- Adjudicator protocol (D3.1) ------------------------------------------------------
class Adjudicator(Protocol):
    """Decides ambiguous-band pairs. Returns True (same entity), False (distinct), or None
    (unsure -> needs_review, kept separate)."""

    def adjudicate(self, name_a: str, name_b: str, score: float) -> Optional[bool]: ...


@dataclass
class RuleBasedAdjudicator:
    """Deterministic default — no API key required. Merges only on strong structural
    evidence: identical cleaned stems, or one stem being a token-prefix of the other with a
    shared, distinctive head token. Otherwise returns None (unsure)."""

    def adjudicate(self, name_a: str, name_b: str, score: float) -> Optional[bool]:
        a, b = clean_name(name_a), clean_name(name_b)
        if not a or not b:
            return None
        if a == b:
            return True
        ta, tb = a.split(), b.split()
        # Shared distinctive head token + one is a prefix subset of the other.
        if ta and tb and ta[0] == tb[0]:
            short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if short == long[: len(short)]:
                return True
        return None  # unsure -> needs_review


@dataclass
class CallableAdjudicator:
    """Adapter so an LLM call (or any function) can serve as an Adjudicator. The function
    receives (name_a, name_b, score) and returns True/False/None. This is where the LLM
    adjudication of the ambiguous band plugs in (spec §2.4)."""

    fn: Callable[[str, str, float], Optional[bool]]

    def adjudicate(self, name_a: str, name_b: str, score: float) -> Optional[bool]:
        return self.fn(name_a, name_b, score)


# --- Union-find -----------------------------------------------------------------------
class _UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


# --- Resolution result ----------------------------------------------------------------
@dataclass
class ResolutionResult:
    canonical_of: dict           # raw name -> canonical name
    cluster_of: dict             # raw name -> cluster id (int)
    needs_review_pairs: list     # list[(raw_a, raw_b, score)] unsure pairs (kept separate)
    low_confidence: set          # raw names whose cluster involved an unsure decision

    def possible_same_vendor_for(self, raw_names) -> list:
        """Subset of needs_review pairs where both members appear in `raw_names` — i.e.
        unresolved pairs that affect this market's winner set (D3.3)."""
        s = set(raw_names)
        return [(a, b, sc) for (a, b, sc) in self.needs_review_pairs if a in s and b in s]


def _block_key(cleaned: str) -> str:
    """Blocking key to avoid O(n^2): first 4 chars of the first token (or whole token).
    Cheap, and good enough to keep true variants in the same block in practice."""
    if not cleaned:
        return ""
    head = cleaned.split()[0]
    return head[:4]


def resolve_entities(
    raw_names,
    crosswalk: Optional[dict] = None,
    adjudicator: Optional[Adjudicator] = None,
    config: EntityResolutionConfig = ER_CONFIG,
) -> ResolutionResult:
    """Cluster raw names into canonical entities (D3.1/D3.2).

    Args:
        raw_names: iterable of raw vendor/department strings.
        crosswalk: optional dict mapping a raw or cleaned name to a forced canonical label
                   (the manual M&A / acronym crosswalk for top-N entities, D3.1).
        adjudicator: decides the ambiguous similarity band; default RuleBasedAdjudicator.
        config: similarity bands (D3.2).
    """
    if adjudicator is None:
        adjudicator = RuleBasedAdjudicator()
    crosswalk = crosswalk or {}

    from collections import Counter
    counts = Counter((r if r is not None else "").strip() for r in raw_names)
    counts.pop("", None)
    uniq = sorted(counts)
    cleaned = {r: clean_name(r) for r in uniq}

    uf = _UnionFind(uniq)
    needs_review_pairs: list = []
    low_confidence: set = set()

    # 1) Force-merge crosswalk members that share a forced canonical label. A name that IS
    #    a crosswalk target (the canonical itself) self-maps, so a variant merges with its
    #    canonical even when no fuzzy bridge exists between them.
    canonical_values = set(crosswalk.values())
    forced_groups: dict = {}
    for r in uniq:
        key = crosswalk.get(r) or crosswalk.get(cleaned[r]) or (r if r in canonical_values else None)
        if key:
            forced_groups.setdefault(key, []).append(r)
    for members in forced_groups.values():
        for m in members[1:]:
            uf.union(members[0], m)

    # 2) Block, then pairwise compare within blocks.
    blocks: dict = {}
    for r in uniq:
        blocks.setdefault(_block_key(cleaned[r]), []).append(r)

    for members in blocks.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                ca, cb = cleaned[a], cleaned[b]
                if not ca or not cb:
                    continue
                score = fuzz.token_sort_ratio(ca, cb)
                if score >= config.auto_merge_at:
                    uf.union(a, b)
                elif score < config.keep_separate_below:
                    continue  # distinct
                else:
                    decision = adjudicator.adjudicate(a, b, score)
                    if decision is True:
                        uf.union(a, b)
                    elif decision is None:
                        # Unsure: keep separate (conservative) but record (D3.2/D3.3).
                        needs_review_pairs.append((a, b, float(score)))
                        low_confidence.add(a)
                        low_confidence.add(b)
                    # decision is False -> distinct, nothing to do.

    # 3) Assign cluster ids and pick a canonical label per cluster.
    root_members: dict = {}
    for r in uniq:
        root_members.setdefault(uf.find(r), []).append(r)

    canonical_of: dict = {}
    cluster_of: dict = {}
    for cid, (root, members) in enumerate(sorted(root_members.items())):
        # Canonical label: a forced crosswalk label if any member has one, else the most
        # frequent raw form (tie-break: shortest then alphabetical, so we prefer a clean
        # "Acme Inc." over a regional variant like "Acme Inc. (Ottawa)").
        forced = next((crosswalk.get(m) or crosswalk.get(cleaned[m]) for m in members
                       if crosswalk.get(m) or crosswalk.get(cleaned[m])), None)
        label = forced or sorted(members, key=lambda m: (-counts[m], len(m), m))[0]
        for m in members:
            canonical_of[m] = label
            cluster_of[m] = cid

    return ResolutionResult(canonical_of, cluster_of, needs_review_pairs, low_confidence)
