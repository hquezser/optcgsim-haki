"""Tests de la détection de format avec des banlists synthétiques injectées."""

from optcgsim_haki.formats import FormatDetector

# Deux formats compétitifs bannissant les sets ST31, + un ban de carte ; pas de format laxiste.
FORMATS = [
    {"formatName": "Standard", "bannedSets": ["ST31"], "bannedCards": ["OP01-999"]},
    {"formatName": "StandardB", "bannedSets": ["ST31"], "bannedCards": ["OP01-999"]},
]


def test_standard_pool_is_compatible():
    det = FormatDetector(formats=FORMATS)
    v = det.detect({"OP09-001", "OP12-006", "EB04-004"})
    assert "Standard" in v.compatible_formats
    assert v.extra_regulation_sets == []
    assert v.verdict.startswith("Standard")


def test_identical_pools_collapse_to_high_confidence():
    # Deux formats au pool identique (sets+cartes bannis identiques) -> confiance haute.
    det = FormatDetector(formats=FORMATS)  # Standard et StandardB sont identiques
    v = det.detect({"OP09-001", "OP12-006"})
    assert v.confidence == "high"
    assert "pool identique" in v.verdict


def test_banned_card_disqualifies():
    det = FormatDetector(formats=FORMATS)
    v = det.detect({"OP09-001", "OP01-999"})  # carte bannie partout
    assert v.compatible_formats == []


def test_extra_regulation_detected():
    det = FormatDetector(formats=FORMATS)
    v = det.detect({"OP09-001", "ST31-005"})  # set banni par tous -> Extra Regulation
    assert "ST31" in v.extra_regulation_sets
    assert "Extra Regulation" in v.verdict
    assert v.confidence == "high"
