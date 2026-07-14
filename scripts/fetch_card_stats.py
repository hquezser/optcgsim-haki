"""Script de maintenance : récupère les stats de cartes depuis optcgapi.com.

Usage   : python scripts/fetch_card_stats.py
Requiert: pip install requests
Génère  : optcgsim_tracker/data/card_stats.json

À relancer à chaque nouveau set (~tous les 2 mois). Commiter le résultat.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import date

try:
    import requests
except ImportError:
    print("Dépendance manquante : pip install requests", file=sys.stderr)
    sys.exit(1)

BASE = "https://optcgapi.com/api"
OUT = pathlib.Path(__file__).parent.parent / "optcgsim_tracker" / "data" / "card_stats.json"

# Endpoints bulk (une requête chacun).
BULK_ENDPOINTS = ["allSetCards", "allSTCards", "allPromoCards", "allDonCards"]


def _get(path: str) -> list[dict]:
    url = f"{BASE}/{path}/"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _extract(cards: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for c in cards:
        cid = c.get("card_set_id")
        if not cid:
            continue
        text = c.get("card_text") or ""
        counter = c.get("counter_amount")
        cost = c.get("card_cost")
        power = c.get("card_power")

        def _int(v):
            try:
                return int(v) if v is not None and str(v).upper() != "NULL" else None
            except (ValueError, TypeError):
                return None

        result[cid] = {
            "counter":  _int(counter),
            "trigger":  "[Trigger]"       in text,
            "blocker":  "[Blocker]"       in text,
            "rush":     "[Rush]"          in text,
            "dbl_atk":  "[Double Attack]" in text,
            "cost":     _int(cost),
            "power":    _int(power),
            "card_type": c.get("card_type"),
            "color":    c.get("card_color"),
            "name":     c.get("card_name"),
            # Texte d'effet brut : sert à classer les effets (retrait de board vs fouille
            # deck/trash/main) côté parser live. Voir card_effects.py.
            "text":     text or None,
        }
    return result


def _fetch_bulk() -> tuple[dict[str, dict], list[str]]:
    """Tente les endpoints bulk en premier (1 requête chacun)."""
    all_cards: dict[str, dict] = {}
    errors: list[str] = []
    for ep in BULK_ENDPOINTS:
        print(f"  GET {ep}...", end=" ", flush=True)
        try:
            cards = _get(ep)
            batch = _extract(cards)
            all_cards.update(batch)
            print(f"{len(batch)} cartes")
        except Exception as e:
            print(f"ERREUR ({e})")
            errors.append(ep)
    return all_cards, errors


def _fetch_per_set() -> dict[str, dict]:
    """Fallback : une requête par set (si allSetCards ne retourne pas tout)."""
    all_cards: dict[str, dict] = {}
    print("  Récupération de la liste des sets...", end=" ", flush=True)
    sets = _get("allSets")
    print(f"{len(sets)} sets")
    for s in sets:
        sid = s.get("set_id", "")
        print(f"  GET sets/{sid}...", end=" ", flush=True)
        try:
            cards = _get(f"sets/{sid}")
            batch = _extract(cards)
            all_cards.update(batch)
            print(f"{len(batch)} cartes")
            time.sleep(0.3)  # courtoisie serveur
        except Exception as e:
            print(f"ERREUR ({e})")
    return all_cards


def main() -> None:
    print("=== fetch_card_stats.py ===")
    print("Étape 1 : endpoints bulk")
    all_cards, errors = _fetch_bulk()

    # Si allSetCards n'a retourné qu'un set (< 500 cartes), on fait le fallback par set.
    set_cards_ep_ok = "allSetCards" not in errors
    if set_cards_ep_ok and len(all_cards) < 500:
        print(f"  allSetCards semble incomplet ({len(all_cards)} cartes) → fallback par set")
        all_cards.update(_fetch_per_set())

    print(f"\nTotal : {len(all_cards)} cartes")
    triggers = sum(1 for v in all_cards.values() if v["trigger"])
    print(f"  dont {triggers} avec [Trigger]")
    counters = sum(1 for v in all_cards.values() if v["counter"])
    print(f"  dont {counters} avec counter > 0")

    payload = {"generated": str(date.today()), "cards": all_cards}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"\n✓ Écrit dans {OUT} ({OUT.stat().st_size // 1024} Ko)")
    print("  → git add optcgsim_tracker/data/card_stats.json && git commit -m 'card_stats: update'")


if __name__ == "__main__":
    main()
