# OPTCGSim Haki

Tracker de statistiques **open-source et gratuit** pour [OPTCGSim](https://optcgsim.com/), le
simulateur du jeu de cartes One Piece. Il analyse les **fichiers de logs locaux** écrits par le jeu
sur ta machine et les transforme en une base SQLite interrogeable, pour produire des statistiques
utiles (winrate par leader, par matchup, impact du mulligan, premier/second, durée…).

> Focus v1 : **PC / macOS / Linux**, via analyse des fichiers système. Pas de modification du jeu,
> pas d'injection, pas d'interception réseau.

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
optcgsim-haki backfill            # importe tout l'historique local -> SQLite
optcgsim-haki stats               # winrate par leader / matchup / mode / ordre / mulligan
optcgsim-haki show <match_id>     # déroulé détaillé d'une partie
optcgsim-haki watch               # suivi live en terminal (fair-play par défaut)
optcgsim-haki dashboard           # dashboard web live (board + archétype adverse) sur :8765
optcgsim-haki import-cards <f>    # référentiel externe de noms (JSON {id:name} ou CSV id,name)

# Analyses avancées
optcgsim-haki matchups            # matrice de matchups par leader
optcgsim-haki elo                 # courbe de rating dans le temps (sparkline)
optcgsim-haki streaks             # séries win/loss, perf par jour, usage des counters
optcgsim-haki mulligan            # garder vs mulligan + impact des cartes d'ouverture (lift)
optcgsim-haki archetype <leader> [cartes...]   # prédit le deck adverse depuis l'historique

# Meta (période de jeu) -> Leader
optcgsim-haki meta                # winrate par meta (OP14.5 / OP15 / OP16…)
optcgsim-haki meta OP16           # détail d'un meta : winrate par leader

# Deckbuilding
optcgsim-haki decks               # liste tes decks (leader, counters)
optcgsim-haki deck <nom>          # stats d'un deck : Category / Cost / Counter / Type (traits)
optcgsim-haki watch-decks         # affiche les stats à chaque sauvegarde de deck (live)
```

## v1 : fiable par défaut, approximatif optionnel

La v1 n'expose **que ce dont on est sûr**. Les informations *fiables* sont toujours affichées ;
les informations *approximatives* (inférées du `Player.log` en direct) sont **masquées par défaut**
et réactivables via des variables d'environnement.

**Toujours affiché (fiable) :**
- toutes les **stats post-match** (logs AutoSaved = vérité terrain) ;
- la **recommandation de mulligan** (lift + shrinkage) ;
- en live : **ton** état (main/board/vie) et l'**info publique** adverse (board joué + trash) ;
- le panneau **défense** (`LIVE_DEFENSE`, ON par défaut) : tes counters/blockers/vie exacts face
  au board adverse *visible*, + counters adverses déjà dépensés (événements publics du log).

**Masqué par défaut (approximatif, inféré du log live) :**

| Flag (`OPTCG_FEATURE_…=1`) | Ce qu'il réactive |
|---|---|
| `LIVE_OPP_HAND` | main adverse reconstruite (dérive sur effets) |
| `LIVE_OPP_LIFE` | vie adverse estimée |
| `LIVE_LETHAL` | solveur de lethal (sur données inférées) |
| `LIVE_MENACES` | menaces probables T+1 |
| `LIVE_TRIGGER_RISK` | risque de trigger |
| `LIVE_ARCHETYPE` | inférence du deck/leader adverse |
| `LIVE_DRAW_ODDS` | odds hypergéométriques de pioche (decklist devinée) |
| `VALUE_SCORE` | Value Score / VPD / Early Value (heuristique) |

```bash
# tout réactiver (usage avancé / perso) :
OPTCG_PROFILE=advanced optcgsim-haki dashboard
# ou au cas par cas :
OPTCG_FEATURE_LIVE_LETHAL=1 OPTCG_FEATURE_VALUE_SCORE=1 optcgsim-haki dashboard
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

Un overlay natif affiche un HUD compact (lethal, menaces T+1, draw odds, vies) **par-dessus le jeu** :
fenêtre **toujours au-dessus**, **sans bordure**, **transparente** et **click-through** (la souris
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
**Ma défense** (mes counters/blockers/vie face au board adverse visible), counters adverses déjà
brûlés (événements publics), leader adverse, decks restants. `--advanced` réactive les panneaux
inférés (lethal offensif avec seuil conditionnel, menaces) ; en **mode exact** (mod), tout
redevient affichable car tout est vrai. Il s'ancre par défaut sur la **bande du chat** du sim,
entre les deux mains. Ajuste avec `--zone` + `--hud-debug` si ta disposition diffère.

Par défaut l'overlay active le **profil avancé** (panneaux inférés : lethal, menaces T+1, draw odds,
vie adverse estimée) — c'est un outil perso. Il **n'affiche jamais la main adverse**. `--fair`
revient au profil sobre. En début de partie il reste léger (peu d'info connue) puis se remplit.

- Un menu **🎴 dans la barre de menus macOS** permet de basculer **interactif ⇄ passe-souris**,
  afficher/masquer, recaler sur le jeu, ou quitter (click-through et interactivité s'excluent).
- Lance OPTCGSim en **fenêtré sans bordure** (un vrai plein écran exclusif passerait au-dessus).
- L'overlay suit automatiquement la position/taille de la fenêtre du jeu.

> Feature optionnelle, macOS d'abord (Windows/Linux plus tard). Si `pip install -e '.[overlay]'`
> n'a pas été fait, la commande l'indique.

## Licence

MIT.
