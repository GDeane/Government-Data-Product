"""Unit tests for rule-based procedure/instrument/commodity normalization (D2.4)."""

from incumbency import normalize


def test_procedure_classification_prose():
    assert normalize.classify_procedure("Open Bidding") == "open_competitive"
    assert normalize.classify_procedure("Competitive - Open") == "open_competitive"
    assert normalize.classify_procedure("Advance Contract Award Notice") == "ACAN"
    assert normalize.classify_procedure("Sole Source") == "sole_source"
    assert normalize.classify_procedure("Selective Tendering") == "selective"


def test_procedure_classification_pd_codes():
    assert normalize.classify_procedure("OB") == "open_competitive"
    assert normalize.classify_procedure("AC") == "ACAN"
    assert normalize.classify_procedure("TN") == "sole_source"
    assert normalize.classify_procedure("ST") == "selective"


def test_procedure_recognition_flags_unknown():
    assert normalize.procedure_is_recognised("Open Bidding") is True
    assert normalize.procedure_is_recognised("OB") is True
    assert normalize.procedure_is_recognised("") is False
    assert normalize.procedure_is_recognised("zzz mystery") is False
    # Unrecognised still classifies (to a flagged default) rather than crashing.
    assert normalize.classify_procedure("zzz mystery") == "open_competitive"


def test_instrument_classification():
    assert normalize.classify_instrument("Standing Offer") == "standing_offer"
    assert normalize.classify_instrument("Call-up against standing offer") == "call_up"
    assert normalize.classify_instrument("Contract") == "contract"
    assert normalize.classify_instrument("") == "contract"  # graceful default (D1.3)


def test_normalize_gsin():
    assert normalize.normalize_gsin(" d302a ") == "D302A"
    assert normalize.normalize_gsin(None) == ""
