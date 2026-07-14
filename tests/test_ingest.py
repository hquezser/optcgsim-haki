"""Tests d'ingestion — rapprochement log AutoSaved <-> ranked (my_matches)."""

from datetime import datetime, timezone

from optcgsim_haki.ingest import _epoch, _MATCH_WINDOW_S


def test_epoch_naive_interpreted_as_utc():
    """Un datetime NAÏF (ts ranked) doit être interprété en UTC, comme l'AWARE des logs.

    Régression du bug TZ : `.timestamp()` sur un naïf l'interprétait en heure locale,
    décalant l'epoch du fuseau (ex. +2h en CEST) et faisant échouer le rapprochement.
    """
    naive = datetime(2026, 6, 27, 22, 26, 9)
    aware = datetime(2026, 6, 27, 22, 26, 9, tzinfo=timezone.utc)
    assert _epoch(naive) == _epoch(aware)


def test_epoch_window_naive_ranked_vs_aware_log():
    """Une partie : ranked (naïf UTC, début) vs log AutoSaved (aware UTC, fin) à ~11 min.

    L'écart doit rester DANS la fenêtre de rapprochement (et non gonflé par le fuseau).
    """
    ranked_start = datetime(2026, 6, 27, 22, 26, 9)                       # naïf (UTC)
    log_end = datetime(2026, 6, 27, 22, 37, 25, tzinfo=timezone.utc)      # aware UTC
    gap = abs(_epoch(log_end) - _epoch(ranked_start))
    assert gap < 15 * 60               # ~11 min, pas ~2h11
    assert gap <= _MATCH_WINDOW_S      # dans la fenêtre -> rapprochement possible


def test_epoch_none():
    assert _epoch(None) is None
