"""Tests des probabilités hypergéométriques (tirage sans remise)."""

import pytest

from optcgsim_tracker.hypergeometric import (
    p_at_least,
    p_at_least_one,
    p_exactly,
    p_mulligan,
)


# --- Vecteurs canoniques (cas d'usage One Piece TCG) ---------------------------------------

def test_searcher_odds():
    # Searcher type Nami : regarde 5 cartes, 10 hits dans un deck de 35 restantes.
    assert p_at_least_one(35, 10, 5) == pytest.approx(0.8363, abs=1e-4)


def test_triggers_in_life():
    # 12 triggers dans 50 cartes, 5 cartes placées en vie -> >=1 trigger.
    assert p_at_least_one(50, 12, 5) == pytest.approx(0.7631, abs=1e-4)


def test_opening_single_card():
    # 4 copies dans 50 cartes, main de 5 -> >=1 copie.
    assert p_at_least_one(50, 4, 5) == pytest.approx(0.3530, abs=1e-4)


def test_mulligan_combines_two_draws():
    # Garder OU mulligan : 1-(1-p)^2 avec p ~= 0.3530.
    assert p_mulligan(50, 4, 5) == pytest.approx(0.5814, abs=1e-4)
    # Toujours >= une seule main, et < 2*p.
    single = p_at_least_one(50, 4, 5)
    assert p_mulligan(50, 4, 5) > single


# --- Cohérence interne ---------------------------------------------------------------------

def test_p_at_least_one_matches_p_at_least_k1():
    assert p_at_least(50, 4, 5, 1) == pytest.approx(p_at_least_one(50, 4, 5))


def test_p_exactly_distribution_sums_to_one():
    total = sum(p_exactly(50, 12, 5, k) for k in range(0, 6))
    assert total == pytest.approx(1.0, abs=1e-9)


def test_p_at_least_decreases_with_k():
    probs = [p_at_least(50, 12, 5, k) for k in range(0, 6)]
    assert probs == sorted(probs, reverse=True)


# --- Cas limites ---------------------------------------------------------------------------

def test_no_copies_is_zero():
    assert p_at_least_one(50, 0, 5) == 0.0
    assert p_mulligan(50, 0, 5) == 0.0


def test_no_draw_is_zero():
    assert p_at_least_one(50, 4, 0) == 0.0


def test_k_zero_is_certain():
    assert p_at_least(50, 4, 5, 0) == 1.0
    assert p_exactly(50, 0, 5, 0) == 1.0


def test_all_cards_are_hits_is_certain():
    assert p_at_least_one(5, 5, 3) == 1.0
    assert p_at_least_one(40, 40, 1) == 1.0


def test_more_hits_than_undrawable_is_certain():
    # K=48 hits dans 50, on tire 5 : impossible de tous les éviter.
    assert p_at_least_one(50, 48, 5) == 1.0


def test_args_are_clamped_not_raising():
    # n et K > N, valeurs négatives -> bornées, pas d'exception.
    assert 0.0 <= p_at_least_one(50, 99, 60) <= 1.0
    assert p_at_least_one(50, -3, 5) == 0.0
    assert p_exactly(0, 0, 0, 0) == 1.0


def test_results_always_in_unit_interval():
    for N, K, n in [(50, 4, 5), (35, 10, 5), (50, 12, 5), (10, 3, 7), (1, 1, 1)]:
        for fn in (lambda: p_at_least_one(N, K, n), lambda: p_mulligan(N, K, n)):
            v = fn()
            assert 0.0 <= v <= 1.0
