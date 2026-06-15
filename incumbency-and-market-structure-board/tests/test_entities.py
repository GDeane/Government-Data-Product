"""Entity-resolution tests — including the measured precision/recall gate (D3.4)."""

from incumbency import entities
from incumbency.entities import RuleBasedAdjudicator, resolve_entities
from labelled_vendor_pairs import LABELLED_PAIRS


def test_clean_name_strips_suffixes_regions_stopwords():
    assert entities.clean_name("Acme Inc. (Ottawa)") == "acme"
    assert entities.clean_name("Deloitte Toronto") == "deloitte"
    assert entities.clean_name("McKinsey & Company") == "mckinsey"
    assert entities.clean_name("Stantec Consulting Ltée") == "stantec consulting"


def test_variants_collapse_to_one_entity():
    names = ["Acme Inc.", "ACME INCORPORATED", "Acme Ltd.", "Acme Inc. (Ottawa)"]
    res = resolve_entities(names)
    assert len({res.cluster_of[n] for n in names}) == 1  # all one cluster


def test_conservative_on_merges_records_needs_review():
    # In-band, non-prefix, shared head -> unsure -> kept separate AND flagged (D3.2/D3.3).
    names = ["Riverbend Analytics Services", "Riverbend Analytics Solutions"]
    res = resolve_entities(names)
    assert res.cluster_of[names[0]] != res.cluster_of[names[1]]   # not merged
    assert len(res.needs_review_pairs) == 1                       # but flagged


def test_crosswalk_forces_ma_merge():
    names = ["Globex Corporation", "Globex Defence Systems"]
    res = resolve_entities(names, crosswalk={"Globex Defence Systems": "Globex Corporation"})
    assert res.cluster_of[names[0]] == res.cluster_of[names[1]]
    assert res.canonical_of[names[1]] == "Globex Corporation"


def test_entity_resolution_precision_recall():
    """The headline accuracy gate: precision >= 0.95 on hand-labelled pairs (D3.4).

    False merges corrupt both concentration and turnover, so precision is the hard target;
    recall is reported and held to a reasonable floor."""
    names = sorted({n for a, b, _ in LABELLED_PAIRS for n in (a, b)})
    res = resolve_entities(names, adjudicator=RuleBasedAdjudicator())

    tp = fp = fn = tn = 0
    for a, b, same in LABELLED_PAIRS:
        predicted_same = res.cluster_of[a] == res.cluster_of[b]
        if same and predicted_same:
            tp += 1
        elif same and not predicted_same:
            fn += 1
        elif not same and predicted_same:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    # Hard gate from the spec (§2.4): false merges are the costly error.
    assert precision >= 0.95, f"precision {precision:.3f} (fp={fp}); merges too aggressive"
    # Sanity floor on recall so the resolver isn't trivially never-merging.
    assert recall >= 0.75, f"recall {recall:.3f} (fn={fn}); merges too timid"
