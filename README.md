# OPTCGSim Haki

**Assistant de décision en cours de match**, open-source et gratuit, pour
[OPTCGSim](https://optcgsim.com/), le simulateur du jeu de cartes One Piece. Il lit les
**fichiers de logs locaux** écrits par le jeu en temps réel et affiche, dans un **overlay HUD**
par-dessus la partie, uniquement de l'information **exacte et publique** utile à la décision :
lethal/défense, cartes adverses déjà vues (règle des 4), aide au mulligan, probabilités de pioche.

> Focus : **la décision en jeu**, pas les statistiques a posteriori. macOS pour l'overlay natif ;
> macOS / Linux / Windows pour le reste. Aucune modification du jeu, pas d'injection, pas
> d'interception réseau — juste la lecture des logs.

## Comment ça marche

OPTCGSim (moteur **Unity**) écrit chaque partie en clair sur le disque :

- `CombatLogs/AutoSaved/*.log` — un fichier par partie (tous modes), écrit en fin de partie.
- `Player.log` (Unity) — le flux en **temps réel** d'une partie en cours.
- `my_matches` (extension **OPBounty**, Godot) — historique des parties classées : decklists
  complètes des deux joueurs, ratings/Elo, durée.

Le tracker parse ces sources, déduit le **format** (Standard / Extra Regulation / Korean…) à partir
des cartes vues, et stocke tout dans SQLite.

## Installation

```bash
# Depuis une release GitHub (recommandé : wheel avec le dashboard pré-buildé, npm inutile) :
pip install optcgsim_haki-<version>-py3-none-any.whl

# Depuis les sources (dev) :
pip install -e .          # + extras dev : pip install -e ".[dev]"
./scripts/build_frontend.sh   # requiert Node >= 20.9 — build le dashboard web embarqué
```

## Utilisation

```bash
optcgsim-haki overlay             # ⭐ overlay HUD de décision par-dessus le jeu (macOS)
optcgsim-haki dashboard           # même moteur, en page web (:8765) — vue live de confort
optcgsim-haki watch               # suivi live d'une partie en cours, dans le terminal
optcgsim-haki backfill            # (pré-requis) construit la base SQLite d'historique local
optcgsim-haki import-cards <f>    # référentiel externe de noms (JSON {id:name} ou CSV id,name)
```

> **Pourquoi `backfill` si l'app n'affiche plus de stats ?** L'historique local reste la
> **donnée d'entraînement** des aides in-match : la reco de mulligan et l'inférence de
> l'archétype/menaces adverses s'appuient dessus. Les *vues* statistiques (winrate, matchups,
> historique de matchs…) ont été retirées ; le moteur qui les calculait nourrit désormais la
> décision en direct.

## Fiable par défaut, inféré en option

Principe : par défaut, l'app n'affiche **que ce dont on est sûr** — l'exact (mes snapshots) et
le public (ce que le jeu a révélé). Les informations *inférées* du `Player.log` (probabilistes,
sujettes à dérive) sont **masquées par défaut** et réactivables par variable d'environnement, ou
d'un coup avec `--advanced` sur l'overlay.

**Toujours affiché (fiable / exact / public) :**
- **Ma défense** (`LIVE_DEFENSE`) : mes counters/blockers/vie exacts face au board adverse
  *visible*, counter requis pour tenir le tour, counters adverses déjà brûlés ;
- **Vu chez l'adversaire** (`LIVE_OPP_SEEN`) : exemplaires joués/défaussés, `n/4` (règle des 4) ;
- **Aide au mulligan** (`MULLIGAN_RECO`) : garder / mulligan sur la main de départ (score vs deck) ;
- le leader adverse **observé** (via ses actions) et les decks restants.

**Masqué par défaut (inféré du log live) :**

| Flag (`OPTCG_FEATURE_…=1`) | Ce qu'il réactive |
|---|---|
| `LIVE_LETHAL` | solveur de lethal offensif (sur données inférées) |
| `LIVE_MENACES` | menaces probables au prochain tour |
| `LIVE_TRIGGER_RISK` | risque de trigger dans les vies adverses |
| `LIVE_ARCHETYPE` | inférence du deck/leader adverse |
| `LIVE_DRAW_ODDS` | odds hypergéométriques de pioche (si decklist non certaine) |
| `LIVE_OPP_HAND` | main adverse reconstruite (dérive sur effets) |
| `LIVE_OPP_LIFE` | vie adverse estimée |

```bash
# tout réactiver (usage avancé / perso) :
OPTCG_PROFILE=advanced optcgsim-haki dashboard
# overlay avec panneaux inférés :
optcgsim-haki overlay --advanced
```

> En **mode état exact** (setup perso avec un mod optionnel, non distribué avec ce dépôt),
> ces panneaux deviennent *exacts* et sont automatiquement réaffichés (badge « ⚡ état exact »).
> `optcgsim_haki/exact_state.py` est le client de ce mode ; il reste inerte sans le mod.

### Données de cartes

Les métadonnées complètes (coût, counter, power, couleur, type, traits) de ~2650 cartes sont
extraites de la base embarquée dans `OPBounty.pck`, complétées par les `Cards/*.json` Unity locaux,
avec mise en cache. Quelques cartes très récentes (dernier set) peuvent manquer tant qu'elles ne
sont pas dans le pck ni en cache local — elles sont alors signalées comme « sans données ».

### Noms de cartes

La base **complète** des noms (≈2700 cartes) est extraite automatiquement de l'asset Unity du jeu
(`resources.assets`, celui qui alimente le deck builder), avec mise en cache. La couverture est
donc totale sans configuration. Si le jeu est installé ailleurs, indique l'asset via la variable
`OPTCG_RESOURCES_ASSETS`.

En complément, `import-cards` permet d'injecter un référentiel externe (JSON `{id:name}` ou CSV
`id,name`) — il ne complète que les noms manquants, sans écraser ceux du jeu :

```bash
optcgsim-haki import-cards cartes.csv
```

## ⚠️ Fair-play & vie privée

- **Mode live fair-play par défaut.** Pendant une partie, le tracker n'affiche que l'**information
  publique** (cartes jouées/révélées, nombre de cartes en main de l'adversaire, life, board).
- Une option `--reveal-all` existe pour la **revue post-match**. Les logs contiennent techniquement
  la main cachée et l'ordre du deck adverse : **utiliser `--reveal-all` pendant une partie classée
  en ligne contre un vrai joueur constitue de la triche.** L'outil affiche un avertissement explicite.
- **Données personnelles** : le tracker ne lit **jamais** `com.Batsu.OPTCGSim.plist` (il contient
  des identifiants et tokens). Les bases de données et les logs bruts sont exclus du dépôt
  (`.gitignore`). Les fixtures de test sont anonymisées.

## Overlay HUD (macOS)

L'overlay est **le produit** : un HUD compact de décision **par-dessus le jeu** — fenêtre
**toujours au-dessus**, **sans bordure**, **transparente** et **click-through** (la souris
traverse l'overlay pour cliquer sur le jeu). C'est une fenêtre OS standard — **aucune injection**,
le jeu ne la voit pas.

```bash
pip install -e '.[overlay]'     # pywebview + pyobjc (macOS)
optcgsim-haki overlay           # démarre l'API + l'overlay (cible la fenêtre « OPTCGSim »)
# options : --owner <nom>  --opacity 0.9  --no-server (si un dashboard tourne déjà)  --port 8765
#           --advanced (réactive les panneaux INFÉRÉS : lethal offensif, menaces, odds estimées)
#           --zone x:6,y:30,w:20,h:50 (position du HUD en % de la fenêtre du jeu)
#           --hud-debug (dessine le contour de la zone pour la caler)
```

Le HUD est **fiable par défaut** : il n'affiche que l'exact/public que le jeu ne montre pas —
**Ma défense** (counters/blockers/vie face au board adverse visible + counter requis pour tenir),
**Vu chez l'adversaire** (exemplaires `n/4`), **aide au mulligan** (pendant la fenêtre de
mulligan), leader adverse observé et decks restants. `--advanced` réactive les panneaux inférés
(lethal offensif avec seuil conditionnel, menaces T+1) ; en **mode exact** (mod), tout redevient
affichable car tout est vrai. Il **n'affiche jamais la main cachée adverse**. Il s'ancre par
défaut sur la **bande du chat** du sim, entre les deux mains ; ajuste avec `--zone` + `--hud-debug`
si ta disposition diffère.

- Un menu **🎴 dans la barre de menus macOS** permet de basculer **interactif ⇄ passe-souris**,
  afficher/masquer, recaler sur le jeu, ou quitter (click-through et interactivité s'excluent).
- Lance OPTCGSim en **fenêtré sans bordure** (un vrai plein écran exclusif passerait au-dessus).
- L'overlay suit automatiquement la position/taille de la fenêtre du jeu.

> Feature optionnelle, macOS d'abord (Windows/Linux plus tard). Si `pip install -e '.[overlay]'`
> n'a pas été fait, la commande l'indique.

## Licence

MIT.
