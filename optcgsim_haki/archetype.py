"""Détection d'archétype/​deck adverse à partir de l'historique.

On dispose de ~770 decklists adverses complètes (parties classées, `decks.known=1`). Pour un
leader donné et un ensemble de cartes déjà révélées, on prédit :
  - le deck "typique" du leader (fréquence des cartes sur l'historique) ;
  - le deck historique le plus proche (recouvrement avec les cartes révélées) ;
  - les cartes à fort taux de présence pas encore vues (susceptibles d'arriver).

Réutilisable par l'overlay live (Phase C) pour annoncer l'archétype tôt.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .db.store import Store


@dataclass
class ArchetypePrediction:
    leader: str
    leader_name: str
    n_historical: int
    expected_cards: list[dict]   # [{card_id, name, presence%, avg_copies}]
    nearest_overlap: float        # 0..1 recouvrement avec le meilleur deck historique
    unseen_likely: list[dict]     # cartes fréquentes pas encore révélées


class ArchetypeModel:
    def __init__(self, store: Store):
        self.s = store
        # decks adverses connus, groupés par leader : leader -> list[dict(card->qty)]
        self._by_leader: dict[str, list[dict[str, int]]] = defaultdict(list)
        # Cache des noms (chargé une fois) -> le modèle devient autonome et thread-safe :
        # predict() ne touche plus la base, ce qui permet de le servir depuis un thread HTTP.
        self._names: dict[str, str] = {
            r["card_id"]: r["name"]
            for r in store.query("SELECT card_id, name FROM cards WHERE name IS NOT NULL")
        }
        self._load()

    def _name(self, cid: str) -> str:
        return self._names.get(cid, cid)

    def _load(self) -> None:
        rows = self.s.query(
            """SELECT m.opp_leader AS lead, d.match_id AS mid, d.card_id AS cid, d.qty AS qty
               FROM decks d JOIN matches m ON m.id = d.match_id
               WHERE d.side='opp' AND d.known=1 AND m.opp_leader IS NOT NULL""")
        by_match: dict[tuple, dict[str, int]] = defaultdict(dict)
        match_leader: dict[str, str] = {}
        for r in rows:
            by_match[r["mid"]][r["cid"]] = r["qty"]
            match_leader[r["mid"]] = r["lead"]
        for mid, deck in by_match.items():
            self._by_leader[match_leader[mid]].append(deck)

    def leaders(self) -> list[str]:
        return list(self._by_leader)

    def infer_leader(self, revealed: set[str]) -> tuple[str | None, float]:
        """Devine le leader adverse à partir des cartes publiques vues (live, sans 'Leader is').

        Renvoie (leader, score) où score = meilleure fraction des cartes vues couverte par un
        deck historique de ce leader.

        Départage des ex-æquo par le CODE DE SET du leader (et non son nom) : plusieurs leaders
        homonymes (ex. Portgas D. Ace OP13-002 / OP16-001) partagent nom ET cartes, donc en
        début de partie (peu de cartes vues) ils sont souvent à égalité de couverture. On
        préfère alors le leader dont le set domine les cartes révélées (cartes OP16 -> leader
        OP16), puis l'ordre alphabétique du card_id. Résultat DÉTERMINISTE -> plus de flip entre
        deux rafraîchissements qui mélangeait les menaces de deux Ace différents.
        """
        if not revealed:
            return None, 0.0
        cov_by_leader: dict[str, float] = {}
        for leader, decks in self._by_leader.items():
            best = max((len(set(deck) & revealed) / len(revealed) for deck in decks),
                       default=0.0)
            if best > 0:
                cov_by_leader[leader] = best
        if not cov_by_leader:
            return None, 0.0
        top = max(cov_by_leader.values())
        candidates = [lid for lid, c in cov_by_leader.items() if abs(c - top) < 1e-9]
        if len(candidates) > 1:
            from collections import Counter
            sets = Counter(c.split("-")[0] for c in revealed if "-" in c)
            dom_set = sets.most_common(1)[0][0] if sets else None
            same_set = [lid for lid in candidates if lid.split("-")[0] == dom_set]
            candidates = same_set or candidates
            candidates.sort()   # déterministe à set égal
        return candidates[0], top

    def predict(self, leader: str, revealed: set[str] | None = None,
                top: int = 15) -> ArchetypePrediction | None:
        decks = self._by_leader.get(leader)
        if not decks:
            return None
        revealed = revealed or set()
        n = len(decks)

        # Profil de fréquence : présence (nb de decks contenant la carte) + copies moyennes.
        presence: dict[str, int] = defaultdict(int)
        copies: dict[str, int] = defaultdict(int)
        for deck in decks:
            for cid, qty in deck.items():
                presence[cid] += 1
                copies[cid] += qty
        expected = [
            {"card_id": cid, "name": self._name(cid),
             "presence": 100 * presence[cid] / n,
             "avg_copies": copies[cid] / presence[cid]}
            for cid in presence
        ]
        expected.sort(key=lambda d: (d["presence"], d["avg_copies"]), reverse=True)

        # Deck historique le plus proche : fraction des cartes RÉVÉLÉES qu'il contient
        # (1.0 = un deck historique contient toutes les cartes déjà vues).
        nearest = 0.0
        if revealed:
            for deck in decks:
                covered = len(set(deck) & revealed) / len(revealed)
                nearest = max(nearest, covered)

        unseen = [c for c in expected if c["card_id"] not in revealed and c["presence"] >= 50]

        return ArchetypePrediction(
            leader=leader, leader_name=self._name(leader), n_historical=n,
            expected_cards=expected[:top], nearest_overlap=nearest,
            unseen_likely=unseen[:top],
        )
