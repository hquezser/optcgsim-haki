# OPTCGSim Tracker — Guide de développement

## Build & Test

```bash
# Tests Python
python3 -m pytest tests/ -q

# Build frontend
cd frontend && npm run build

# Build package (wheel + sdist)
python3 -m build

# Installer en dev (editable)
pip install -e .

# Installer depuis le wheel
pip install dist/optcgsim_tracker-0.1.0-py3-none-any.whl
```

## Architecture

- `optcgsim_tracker/` — package Python (backend)
  - `cli.py` — entry point `optcg-tracker`
  - `engine.py` — LiveEngine (tail Player.log, payload /state, solveur de lethal)
  - `api/server.py` — serveur FastAPI (API + frontend statique)
  - `resources.py` — résolution des ressources embarquées (importlib.resources)
  - `paths.py` — résolution multiplateforme des chemins OPTCGSim
  - `static/` — frontend Next.js pré-buildé (généré par `scripts/build_frontend.sh`)
- `frontend/` — app Next.js (dashboard)
- `tests/` — tests pytest

## Packaging

### Pré-requis pour publier sur PyPI

1. **Build le frontend** :
   ```bash
   ./scripts/build_frontend.sh
   ```
   Ce script lance `npm run build` puis copie `frontend/out/` vers `optcgsim_tracker/static/`.

2. **Build le package** :
   ```bash
   python3 -m build
   ```
   Produit `dist/optcgsim_tracker-0.1.0-py3-none-any.whl` + `dist/optcgsim_tracker-0.1.0.tar.gz`.

3. **Publier** :
   ```bash
   twine upload dist/*
   ```

4. **Installation utilisateur** :
   ```bash
   pip install optcgsim-tracker
   # ou
   pipx install optcgsim-tracker
   # ou
   uv tool install optcgsim-tracker
   ```

### Résolution des ressources

Le module `optcgsim_tracker/resources.py` résout le chemin du frontend statique :

1. **Priorité 1** : `optcgsim_tracker/static/` (dans le package — après `pip install`)
2. **Priorité 2** : `frontend/out/` (racine du repo — mode dev)

Utilise `importlib.resources` pour fonctionner dans tous les cas (editable install,
pip install, wheel, mode dev depuis le repo).

### Fichiers embarqués dans le wheel

- `optcgsim_tracker/static/**` — frontend Next.js pré-buildé (via `package-data` dans `pyproject.toml`)
- `LICENSE` — licence MIT (via `MANIFEST.in`)

### Fichiers NON embarqués (générés au runtime)

- `optcg.db` — base SQLite utilisateur (créée par `optcg-tracker backfill`)
- `*.cardmeta.json` / `*.cardnames.json` — caches générés depuis `resources.assets` du jeu

### .gitignore

`optcgsim_tracker/static/` et `frontend/out/` sont ignorés : ce sont des artefacts
de build, régénérés par `scripts/build_frontend.sh`. Ne pas committer.

## Solveur de Lethal

Le module `engine.py` contient deux fonctions complémentaires :

- `_compute_lethal` — simulation du combat (compte les vies perdues/infligeables)
- `_solve_lethal` — solveur d'optimisation (allocation DON!! + plan d'attaque)

`_build_lethal_payload` utilise les deux :
- `opp_can_lethal` / `lives_at_risk` → `_compute_lethal` (perspective défenseur)
- `me_can_lethal` / `me_attack_plan` / `me_don_needed` → `_solve_lethal` (perspective attaquant)
- `me_lethal_prob` → `(1 - trigger_risk/100)^opp_life` (risque de trigger sur les vies)

### Équations

- **A (largeur)** : `N_requis = vies + blockers + 1` (coup de grâce)
- **B (coût DON)** : `C_don(P, T) = max(0, ceil((T - P) / 1000))`
- **C (optimisation)** : tri décroissant attaquants ↔ cibles, somme des coûts ≤ DON dispo

## Modèle de Mulligan (v2)

Le module `analytics.py` contient le moteur de recommandation de mulligan.

### Pipeline

1. **`opening_impact`** — mesure brute par carte : `lift = WR(c en main) − WR(baseline)`
   - DWR (Draw Winrate), PRO (Play-Rate), Dead-in-Hand WR
2. **`mulligan_reco`** — shrinkage bayésien + malus + split Premier/Second
3. **`score_hand`** — score d'une main avec Curve Penalty
4. **`engine.py`** — verdict Garder/Mulligan avec seuils relatifs

### Améliorations v2 (vs v1)

| # | Problème | Solution | Fichier |
|---|----------|----------|---------|
| 1 | **Syndrome de la brique** : 4 boss à cost 8 = score élevé mais injouable | **Curve Penalty** : -3 si 3 cartes ≥5 cost, -6 si 4+ | `score_hand()` |
| 2 | **Seuils absolus** (±5) : un deck instable à moyenne -2 ne mulligan jamais | **Seuils relatifs** : Garder si `score > avg_deck + 3`, Mulligan si `score < avg_deck - 3` | `engine.py` |
| 3 | **k=5 trop sensible** : 5 matchs de matchup = même poids que l'historique global | **k=20** : absorbe la variance (triggers, mulligans adverses) | `mulligan_reco()` |
| 4 | **Dead-in-Hand non exploité** : carte jamais jouée mais WR élevé = passager clandestin | **Malus Dead-in-Hand** : si `|dwr_dead − DWR| < 3%`, divise le lift par 2 | `_shrinkage_scored()` |

### Équations

**Shrinkage** : `score = (n_mu × lift_mu + k × lift_global) / (n_mu + k)` avec `k=20`

**Curve Penalty** :
- 0-2 cartes ≥5 cost → pas de malus
- 3 cartes ≥5 cost → `-3`
- 4+ cartes ≥5 cost → `-6`

**Dead-in-Hand** : si `n_dead ≥ 2` et `|dwr_dead − DWR| < 3%` → `score /= 2`

**Seuils relatifs** :
- `score ≥ avg_hand + 3` → Garder
- `score ≤ avg_hand - 3` → Mulligan
- sinon → Neutre
- Fallback ±5 absolu si pas assez d'historique (< 3 mains)

## Value Score (State Diffing)

Le Value Score mesure l'impact réel d'une carte à l'instant T, contrairement au
Winrate/Lift qui ne mesurent que le résultat final. Implémenté dans `analytics.py`.

### Principe

Pour chaque `deploy` d'une carte X par le camp "me" :
1. **Snap A** : état reconstruit juste avant le deploy (main, board, DON, vies)
2. **Résolution** : les events jusqu'au `end_turn` suivant sont attribués à X, sous
   conditions d'**attribution causale** (voir ci-dessous)
3. **Diff** : `Value = Σ(effets positifs) - coût investi`

### Attribution causale (anti-faux-crédit)

Tout event de la fenêtre n'est pas l'œuvre de la carte posée. Garde-fous dans `_diff_value` :

- **KO / trash adverse** : crédité seulement s'il survient **avant** la 1re attaque "me" de la
  fenêtre (`after_attack=False`) → un KO post-attaque relève du **combat** (corps déjà en jeu),
  pas de l'effet OnPlay de la carte.
- **`effect_remove`** : crédité seulement si **la source = la carte déployée** (`card_id == X`) →
  on n'attribue pas à X un retrait initié par une autre carte tombé dans sa fenêtre.
- **Body** (`power/1000`) : non crédité si la carte est elle-même **retirée dans sa propre
  fenêtre** (`self_removed`) → jouée dans un removal = aucun corps durable.

### Matrice de conversion (1 DON!! = 1 point)

| Axe | Event | Points |
|-----|-------|--------|
| Card Advantage | `draw` par moi | +2 par carte |
| Card Advantage | `counter` adverse | +2 (défausse adverse) |
| Tempo | `ko` / `effect_remove` / `trash_bare` adverse | +cost du perso détruit |
| Body | deploy (corps sur board) | +power/1000 (sauf si retiré le tour même) |
| Life Advantage | `life_damage` infligé | +2 par vie |
| Investissement | deploy (DON dépensé) | -cost de la carte |

> Pas de poids `life_heal` : aucun event de soin n'est produit par le parser (nécessiterait
> d'abord un event dédié dans `match.py`).

### Nouveaux events parser (étape 1)

Le parser `match.py` capture maintenant ces events supplémentaires :

| Type | Ligne de log | `side` = | Sémantique |
|------|-------------|----------|------------|
| `ko` | `Card [id] Destroyed` | propriétaire (victime) | KO en combat ou par effet |
| `effect_remove` | `Source [sid]: Trash/Return/Send Cible [tid]` | propriétaire de la **cible** (victime) | retrait par effet, `card_id`=source, `target_id`=cible, `value`=verb (1=trash, 2=bounce, 3=deck). Crédité seulement si `side='opp'` (victime adverse) ET source = carte déployée — exclut le self-trash de coût |
| `trash_bare` | `Trash Card [id]` | propriétaire (victime) | remplacement board plein |
| `life_damage` | `Card [id] hit for N damage` | attaquant | dégâts de vie, `value` = nb vies |
| `attack_fail` | `Attack Fails` | dernier attaquant | attaque échouée (counter gagné) |

### Endpoint API

- `GET /api/value-stats?leader=X&meta=Y` → `[{card_id, name, n, avg_value, avg_value_win, avg_value_loss, avg_cost}]`
- Aussi inclus dans `GET /api/stats` au niveau détail sous `value_scores`

## Modifier Engine (buffs de puissance)

Le LiveState maintient une pile de modificateurs par entité (leader + characters) pour
calculer la power exacte à l'instant T. Implémenté dans `live.py`.

### Architecture

Chaque `LivePlayer` a un champ `modifiers: dict[card_id, list[Modifier]]`.

```python
@dataclass
class Modifier:
    source_id: str      # carte qui a appliqué le buff
    mod_type: str       # "ADD" (delta) ou "SET_BASE" (remplace la base — non émis par le parser)
    value: int          # valeur en puissance OPTCG
    expiry: str         # CURRENT | NEXT | OWN_NEXT | PERMANENT (voir GC)
    applied_at_turn: int
    applied_by_side: str  # "me" | "opp"
```

### Getter : `get_current_power(player, card_id, base_power)`

Ordre de résolution :
1. Prendre la power originale (`base_power`)
2. Appliquer les `SET_BASE` (le plus récent écrase)
3. Appliquer les `ADD` (somme de tous les buffs/malus)

> Le mécanisme `SET_BASE` existe dans le getter mais **n'est pas produit par le parser**
> (voir ci-dessous) ; il reste utilisable pour un réglage manuel/futur.

### Garbage collection

Hook sur `End Turn` dans `feed_line()` (`_gc_modifiers` est appelé AVANT l'incrément de
`self._turn`, donc `self._turn` = numéro du tour qui se termine) :
- `END_OF_CURRENT_TURN` : expire quand le camp applicateur termine son tour
- `END_OF_NEXT_TURN` (« opponent's next turn ») : expire à la fin du tour adverse suivant
- `END_OF_OWN_NEXT_TURN` (« your next turn ») : expire à la fin du **propre** prochain tour de
  l'applicateur (~2 tours plus tard, un tour adverse intercalé) — `ending_side == applicateur
  AND self._turn > applied_at_turn`
- `PERMANENT` : jamais supprimé

### Parser des buffs

Regex `RE_GRANT_POWER` dans `loglines.py` capture :
```
Source [sid]: Grant/Give Cible [tid] <value> until <expiry>
```

Exemple réel : `Zeff [EB04-004]: Grant Sanji [PRB01-001] 2000 until opponent's next turn end`

**`mod_type` = toujours `ADD`.** Le log émet TOUJOURS un delta additif, jamais une power
absolue — y compris pour les cartes « base power becomes X ». Preuve : EB04-004, dont le texte
est « Your Leader's base power becomes 7000 », est loggé `Grant Sanji 2000` (le delta 7000−5000
vers la base 5000 de Sanji). L'ancien seuil `value >= 5000 → SET_BASE` était donc un **bug** :
il écrasait la base avec le delta (un +6000 ponctuel devenait `base=6000` au lieu de
`5000+6000=11000`), sous-évaluant la power et faisant **manquer des lethals** au solveur.

### Intégration dans le solveur de Lethal

`_build_lethal_payload` accepte un paramètre `live_state` et utilise `get_current_power()`
au lieu de la power statique de la table `cards`. Le solveur voit donc les buffs temporaires
et calcule un lethal correct même si un leader est buffé à 7000 au lieu de 5000.

### Export API

Le payload `/api/state` inclut `modifiers` par joueur :
```json
{"modifiers": {"PRB01-001": [{"source": "EB04-004", "type": "ADD", "value": 2000, "expiry": "END_OF_NEXT_TURN"}]}}
```
