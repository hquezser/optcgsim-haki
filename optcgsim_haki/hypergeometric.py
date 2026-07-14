"""Probabilités hypergéométriques (tirage SANS remise) — l'outil mathématique du TCG.

Quatre variables :
  N : population totale (cartes restantes dans le deck, ex. 50 au début) ;
  K : nombre de copies de la carte recherchée encore dans le deck ;
  n : taille de l'échantillon tiré (5 pour une main d'ouverture, 1 pour une pioche de tour) ;
  k : nombre de succès ciblés (souvent 1).

Module pur (uniquement `math.comb`), sans dépendance, sans effet de bord. Toutes les fonctions sont
défensives : entrées incohérentes -> probabilité bornée dans [0, 1], jamais d'exception.
"""

from __future__ import annotations

from math import comb


def _clamp_args(N: int, K: int, n: int) -> tuple[int, int, int]:
    """Normalise (N, K, n) : entiers >= 0, K et n bornés à N."""
    N = max(0, int(N))
    K = min(max(0, int(K)), N)
    n = min(max(0, int(n)), N)
    return N, K, n


def p_exactly(N: int, K: int, n: int, k: int) -> float:
    """P(exactement k succès) = C(K,k)·C(N-K,n-k) / C(N,n)."""
    N, K, n = _clamp_args(N, K, n)
    if N == 0 or n == 0:
        return 1.0 if k == 0 else 0.0
    if k < 0 or k > K or k > n or (n - k) > (N - K):
        return 0.0
    return comb(K, k) * comb(N - K, n - k) / comb(N, n)


def p_at_least(N: int, K: int, n: int, k: int = 1) -> float:
    """P(au moins k succès) = somme des P(exactement i) pour i de k à min(n, K)."""
    N, K, n = _clamp_args(N, K, n)
    if k <= 0:
        return 1.0
    top = min(n, K)
    if k > top:
        return 0.0
    return sum(p_exactly(N, K, n, i) for i in range(k, top + 1))


def p_at_least_one(N: int, K: int, n: int) -> float:
    """P(au moins 1 succès) = 1 - C(N-K, n)/C(N, n). Le cas le plus courant.

    Forme complémentaire (probabilité de n'en tirer AUCUN), plus rapide et stable que la somme.
    """
    N, K, n = _clamp_args(N, K, n)
    if K == 0 or n == 0:
        return 0.0
    if K >= N:                      # toutes les cartes sont des succès
        return 1.0
    if n > N - K:                   # impossible d'éviter tous les succès
        return 1.0
    return 1.0 - comb(N - K, n) / comb(N, n)


def p_mulligan(N: int, K: int, hand: int = 5) -> float:
    """P(voir >=1 copie sur la main d'ouverture OU après mulligan).

    Règle OPTCG : on pioche `hand` cartes, le mulligan rend toute la main et en repioche `hand`
    (deck remélangé). On voit la carte si la 1re main OU la 2e la contient :
        P = p + (1-p)·p = 1 - (1-p)²   avec p = P(>=1 sur une main).
    """
    p = p_at_least_one(N, K, hand)
    return 1.0 - (1.0 - p) ** 2
