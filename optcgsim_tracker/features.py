"""Système de feature flags pour OPTCGSim Tracker.

v1 : par défaut on n'expose QUE le fiable. Les features "approximatives" (inférées
du log) sont OFF ; activables individuellement via ``OPTCG_FEATURE_<NOM>=1``, ou
toutes ensemble via ``OPTCG_PROFILE=advanced``.

En mode "état exact" (mod BepInEx), les panneaux live deviennent fiables et sont
forcés ON par l'engine (voir ``LiveEngine._apply_feature_gating``).
"""

import os

# Defaults : True = fiable (exposé par défaut), False = approximatif (masqué par défaut).
_DEFAULTS = {
    "stats": True,
    "mulligan_reco": True,
    # Défense : ma vie/counters/blockers (MES snapshots = exacts) face au board adverse
    # VISIBLE (cartes posées = publiques). Fiable -> ON par défaut.
    "live_defense": True,
    "live_opp_hand": False,
    "live_opp_life": False,
    "live_lethal": False,
    "live_menaces": False,
    "live_trigger_risk": False,
    "live_archetype": False,
    "live_draw_odds": False,
    "value_score": False,
}


def feature(name: str) -> bool:
    """Retourne l'état d'un feature flag.

    Priorité :
      1. ``OPTCG_PROFILE=advanced`` → tout ON.
      2. ``OPTCG_FEATURE_<NOM>`` → override explicite (1/true/yes = ON, 0/false/no/'' = OFF).
      3. défaut ``_DEFAULTS``.
    """
    if os.environ.get("OPTCG_PROFILE", "").lower() == "advanced":
        return True
    env = os.environ.get("OPTCG_FEATURE_" + name.upper())
    if env is not None:
        return env not in ("0", "false", "False", "no", "")
    return _DEFAULTS.get(name, False)


def all_features() -> dict:
    """Retourne l'état de tous les flags connus."""
    return {k: feature(k) for k in _DEFAULTS}
