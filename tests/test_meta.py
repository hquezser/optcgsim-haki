"""Tests du rattachement d'une partie à son meta."""

from optcgsim_haki.meta import Meta, card_meta, meta_of, resolve_meta

TIMELINE = [
    Meta("OP14", "OP14", "2026-01-16"),
    Meta("EB03", "OP14.5 (EB03)", "2026-02-20"),
    Meta("OP15", "OP15", "2026-04-03"),
    Meta("OP16", "OP16", "2026-06-12"),
]


def test_meta_of_picks_latest_release_before_date():
    assert meta_of("2026-01-20", TIMELINE).label == "OP14"
    assert meta_of("2026-03-01T10:00:00", TIMELINE).label == "OP14.5 (EB03)"
    assert meta_of("2026-04-03", TIMELINE).label == "OP15"          # jour de sortie
    assert meta_of("2026-06-18T16:47:22", TIMELINE).label == "OP16"


def test_meta_of_edge_cases():
    assert meta_of("2025-01-01", TIMELINE) is None                  # avant tout
    assert meta_of(None, TIMELINE) is None
    assert meta_of("2026-05-01", []) is None


RELEASE = {"OP14": "2026-01-16", "EB03": "2026-02-20", "OP15": "2026-04-03", "OP16": "2026-06-12"}


def test_resolve_meta_handles_early_access_queue():
    # Partie jouée en période OP15 mais avec des cartes OP16 (queue anticipée) -> OP16.
    early = resolve_meta("2026-06-11T20:00:00", {"OP16-022", "OP15-001"}, TIMELINE, RELEASE)
    assert early.label == "OP16"
    # Partie OP15 normale (cartes <= OP15) -> reste OP15.
    normal = resolve_meta("2026-05-01", {"OP15-010", "OP12-008"}, TIMELINE, RELEASE)
    assert normal.label == "OP15"
    # En période OP16 avec uniquement de vieilles cartes -> OP16 (la date prime).
    late = resolve_meta("2026-06-20", {"OP12-008"}, TIMELINE, RELEASE)
    assert late.label == "OP16"


def test_card_meta_picks_newest_set():
    assert card_meta({"OP14-001", "OP16-003"}, TIMELINE, RELEASE).label == "OP16"
    assert card_meta({"OP12-008"}, TIMELINE, RELEASE) is None  # set absent de RELEASE
