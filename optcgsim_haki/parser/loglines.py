"""Tokenizer des lignes texte d'un CombatLog OPTCGSim.

Les lignes sont auto-descriptives (voir la spec dans le plan). On expose des regex compilées et
des helpers de normalisation. Le parser de match (`match.py`) consomme ces tokens.
"""

from __future__ import annotations

import re

# Les pseudos contiennent un espace de largeur nulle (U+200B) avant le '#'. On le retire.
ZERO_WIDTH = "​"


def clean(text: str) -> str:
    return text.replace(ZERO_WIDTH, "").strip()


# cardID : préfixe set (2-4 lettres + 2 chiffres) + '-' + 3 chiffres, OU promo 'P-xxx'.
CARD_ID = r"(?:P-[A-Z0-9]+|[A-Z]{2,4}\d{2}-\d{3})"
CARD_RE = re.compile(rf"\b({CARD_ID})\b")

# Carte référencée : Name [<mark><link="ID">ID</link></mark>]  ->  on capte nom + id.
CARD_REF = re.compile(rf'(?P<name>[^\[\]]*?)\s*\[<mark><link="(?P<id>{CARD_ID})">')

# Préfixe de ligne attribuée à un joueur : "[Pseudo#1234] reste..."
# En Solo vs Self, le préfixe est "[]" (vide) — on l'accepte avec [^\]]* au lieu de [^\]]+.
PLAYER_LINE = re.compile(r"^\[(?P<who>[^\]]*)\]\s*(?P<rest>.*)$")
# Un vrai tag joueur contient '#' + 3-4 chiffres (filtre les tags Unity [ReplaySync]...).
_PLAYER_TAG = re.compile(r"#\d{3,4}")


def is_player_tag(who: str) -> bool:
    return bool(_PLAYER_TAG.search(who))


def is_solo_tag(who: str) -> bool:
    """True si le tag est vide (mode Solo vs Self — préfixe [])."""
    return who == ""

# --- En-tête ---
RE_CONNECT = re.compile(r"^Attempting to connect to (?P<code>\S+)")
RE_VERSION = re.compile(r"^Version is (?P<ver>\S+)")
RE_CONNECTED = re.compile(r"^(?P<who>.+?) Has Connected")

# --- Lignes joueur (à appliquer sur 'rest' après PLAYER_LINE) ---
RE_LEADER = re.compile(rf'^Leader is (?P<name>.*?)\s*\[<mark><link="(?P<id>{CARD_ID})">')
RE_HAND_BEFORE_MULL = re.compile(r"^Hand before Mulligan:\s*\[(?P<ids>[^\]]*)\]")
RE_MULLIGAN = re.compile(r"^Mulligan\b")
RE_GO_ORDER = re.compile(r"^Chose to go (?P<order>First|Second)")
RE_SELECT_ORDER = re.compile(r"^Will select turn order")
RE_DREW_REVEAL = re.compile(rf'^Drew card from deck:\s*(?P<name>.*?)\s*\[<mark><link="(?P<id>{CARD_ID})">')
RE_DRAW_GENERIC = re.compile(r"^Draw (?P<n>\d+) (?P<what>Card|Don)")
RE_DEPLOY = re.compile(rf'^Deploy\s+(?P<name>.*?)\s*\[<mark><link="(?P<id>{CARD_ID})">')
RE_ATTACH_DON = re.compile(r"^Attach (?P<n>\d+) (?:Rested )?Don")
RE_ATTACK = re.compile(
    rf'^.*?\[<mark><link="(?P<att>{CARD_ID})">.*?attacking .*?\[<mark><link="(?P<def>{CARD_ID})">'
)
# Tutor/pioche PUBLIQUE : "<Source> [id]: Reveal and Draw <Nom> [id]". La carte piochée
# (2e lien, celui APRÈS "Reveal and Draw") entre en main avec identité RÉVÉLÉE — info publique
# (fair-play OK, contrairement aux pioches RZ1 privées). On capture l'id de la carte piochée.
RE_REVEAL_DRAW = re.compile(rf'Reveal and Draw\b.*?\[<mark><link="(?P<id>{CARD_ID})">')
RE_COUNTER = re.compile(rf'^Discard\s+.*?\[<mark><link="(?P<id>{CARD_ID})">.*?for Counter (?P<val>\d+)')
# Event [Counter] joué en défense depuis la main : "<Nom> [id]: Activate Counter".
# Distinct du counter de coin (RE_COUNTER) : pas de valeur, et la carte n'est PAS défaussée
# par "Discard ... for Counter". Sans ça, un Event joué au dernier tour passe pour "mort en main".
RE_ACTIVATE_COUNTER = re.compile(
    rf'^(?P<name>.*?)\s*\[<mark><link="(?P<id>{CARD_ID})">.*?\]:\s*Activate Counter\b')
RE_END_TURN = re.compile(r"^End Turn\b")
RE_CONCEDE = re.compile(r"^Concedes!")
RE_WINS = re.compile(r"^Wins!")

# --- Retraits du board (à appliquer sur 'rest' ; le préfixe [Pseudo] = propriétaire) ---
# KO en combat ou par effet : "<Nom> [<id>] Destroyed" -> la carte quitte le board (-> trash).
RE_DESTROYED = re.compile(rf'^.*?\[<mark><link="(?P<id>{CARD_ID})">.*?\bDestroyed\b')
# Effet de retrait du board, attribué à une CIBLE (le 2e id, après le verbe) :
#   "<Source> [sid]: Trash <Cible> [tid]"
#   "<Source> [sid]: Return/Send <Cible> [tid] to Hand"          (bounce)
#   "<Source> [sid]: Return/Send/Sent <Cible> [tid] to Deck Bottom"
# Le verbe doit être suivi d'une référence de carte : "Send 1 Life to Hand", "Added 1 Cards to
# Hand", "Trash 5 Cards from Deck" n'ont pas de lien -> non capturés (pas un retrait de board).
# Capture la SOURCE (1re référence, avant ':') et la CIBLE (après le verbe). La source sert à
# vérifier, via son texte d'effet (card_effects.py), que l'effet retire bien un Character du board.
RE_EFFECT_REMOVE = re.compile(
    rf'^[^[]*\[<mark><link="(?P<src>{CARD_ID})">[^:]*?:\s*'
    rf'(?P<verb>Trash|Return|Sen[dt])\s+[^[]*?\[<mark><link="(?P<id>{CARD_ID})">'
)
# NB : "Add <X> [id] to top of Life" N'EST PAS un retrait de board — la carte vient du deck
# (Shiryu regarde le top) ou de la trash (Gecko Moria), pas du board. La ligne ne précise pas
# la zone source ; on s'appuie donc uniquement sur la présence réelle au board (garde dans
# live.py). Aucun pattern dédié à "to Life".
# Counter joué depuis la MAIN (pas un retrait de board) : on l'exclut explicitement.
# La ligne porte la valeur ("... for Counter 2000") -> capturée pour le comptage public
# et exact des counters dépensés par joueur.
RE_DISCARD_COUNTER = re.compile(r"^Discard\b.*\bfor Counter(?:\s+(?P<val>\d+))?\b")
# Trash « nu » (sans carte source, sans ':') : remplacement board plein (le joueur trash un de
# ses personnages pour poser un 6e). Attribué au propriétaire (préfixe) — retrait de board, comme
# Destroyed. Distinct de l'effet "Source [sid]: Trash ..." dont le rest commence par la source.
RE_TRASH_BARE = re.compile(rf'^Trash\s+[^[]*?\[<mark><link="(?P<id>{CARD_ID})">')

# --- Buffs de puissance (Modifier Engine) ---
# Format : "Source [sid]: Grant Cible [tid] <value> until <expiry>"
# Exemple : "Zeff [EB04-004]: Grant Sanji [PRB01-001] 2000 until opponent's next turn end"
# La valeur est en puissance OPTCG (2000 = +2000 power). Le verbe peut être "Grant" ou "Give".
# On capture : source, cible, valeur, et le texte d'expiry brut (interprété plus tard).
RE_GRANT_POWER = re.compile(
    rf'^(?P<sname>.*?)\s*\[<mark><link="(?P<src>{CARD_ID})">[^:]*?:\s*'
    rf'(?:Grant|Give)\s+(?P<tname>.*?)\s*\[<mark><link="(?P<tgt>{CARD_ID})">'
    rf'[^\]]*?\]\s*(?P<val>-?\d+)\s*(?:power\s*)?until\s+(?P<expiry>.+?)$'
)
# Variante sans cible explicite (buff de zone, ex: "Give all your Characters +1000")
# — non géré en v1 (trop rare dans les logs, l'effet est sur une cible unique).

# --- Snapshots (lignes joueur) ---
RE_HAND = re.compile(r"^Hand:\s*\[(?P<ids>[^\]]*)\]")
RE_BOARD = re.compile(r"^Board:\s*\[(?P<ids>[^\]]*)\]")
RE_TRASH = re.compile(r"^Trash:\s*\[(?P<ids>[^\]]*)\]")
RE_LIFE = re.compile(r"^Life:\s*(?P<life>\d+)")

# --- Lignes globales (non attribuées) ---
RE_VS = re.compile(
    rf'^.*?\[<mark><link="(?P<att>{CARD_ID})">.*?\]\[(?P<ap>\d+)\] vs .*?\[<mark><link="(?P<def>{CARD_ID})">.*?\]\[(?P<dp>\d+)\]'
)
RE_HIT = re.compile(r"hit for (?P<dmg>\d+) damage")
RE_ATTACK_FAILS = re.compile(r"^Attack Fails")
RE_DISCONNECT = re.compile(r"Opponent Has Disconnected")

# Ligne du flux structuré.
RE_RZ1 = re.compile(r"^(?:\[ReplaySync\]\s*)?RZ1\|")

# --- Spécifique Player.log (live) : certaines lignes n'ont PAS de préfixe [Pseudo] ---
# Début de partie FIABLE en direct : émis une seule fois par partie, juste avant les shuffles.
# Contrairement à "RZ1|HDR" (ré-émis par le flux [ReplaySync] lors des resync / retour menu),
# c'est un marqueur sans ambiguïté du démarrage d'une nouvelle partie.
RE_DECK_FILLED = re.compile(r"^deck filled, do shuffle")
# MON deck, loggé en clair à la sélection (avant les shuffles) : identité EXACTE de ma
# decklist (fichier <app_support>/<name>.txt) et donc de mon leader.
RE_PLAYING_DECK = re.compile(r"^Playing with deck:\s*(?P<name>.+?)\s*$")
# Variante émise au DÉMARRAGE de l'app (session restaurée, pas de sélection) : "Load LUD <name>"
# (Last Used Deck). Sans elle, une session restaurée n'a AUCUNE ligne d'identité de deck —
# constaté sur un vrai log online : me_leader restait inconnu et _observed_opp_leader
# attribuait MON leader (vu dans mes actions V3) à l'adversaire.
RE_LOAD_LUD = re.compile(r"^Load LUD\s+(?P<name>.+?)\s*$")
# Activation d'une action V3 (attaque/effet). Les LEADERS y apparaissent quand ils agissent :
# c'est la seule ligne du Player.log live qui révèle l'identité du leader ADVERSE (exacte,
# publique). Le suffixe <N> n'est PAS un index de joueur fiable (mes events counter aussi en
# <0>) : l'attribution se fait côté engine (id de type leader ≠ mon leader -> adverse).
RE_V3_USING = re.compile(rf'^Start Using V3 Action \[.*?\[<mark><link="(?P<id>{CARD_ID})">')
# Solo vs Self : le tag est vide ("shuffle deck for " sans nom). On accepte .* au lieu de .+.
RE_SHUFFLE_FOR = re.compile(r"^shuffle deck for (?P<who>.*)$")
# "Hand before Mulligan: [...]" apparaît SANS préfixe joueur dans Player.log.
RE_HAND_BEFORE_MULL_BARE = re.compile(r"^Hand before Mulligan:\s*\[(?P<ids>[^\]]*)\]")
# Solo vs Self : "Hand after Mulligan: [...]" (sans préfixe) remplace "Hand before Mulligan".
RE_HAND_AFTER_MULL_BARE = re.compile(r"^Hand after Mulligan:\s*\[(?P<ids>[^\]]*)\]")
RE_KEEP = re.compile(r"^chose to keep")
# Solo vs Self : "start action phase for player (N)" indique le joueur actif (0-indexé).
# Sert de signal de gameplay (_played) et d'indice d'attribution pour les snapshots [].
RE_START_ACTION_PHASE = re.compile(r"^start action phase for player \((?P<pnum>\d+)\)")


def parse_id_list(s: str) -> list[str]:
    """'OP09-020,PRB02-002' -> ['OP09-020','PRB02-002'] (filtre les ids valides)."""
    if not s.strip():
        return []
    return [m.group(1) for tok in s.split(",") if (m := CARD_RE.search(tok))]
