/**
 * Définitions des termes statistiques — équivalent des _T_* de liveserver.py.
 *
 * Centralisé pour réutilisation across tous les composants et pages.
 */

export const STATS_TIPS = {
  ci: "Intervalle de confiance à 95% sur le lift. Rouge > 30% = résultat peu fiable. Orange > 15% = interpréter avec prudence.",
  n: "Nombre de parties. En dessous de 20 les statistiques sont bruitées.",
  mode_turn: "Tour le plus fréquent (mode statistique) de premier déploiement. Plus fiable que la moyenne sur des distributions bimodales.",
  baseline: "Baseline conditionnée : winrate des parties ayant duré ≥ ce tour. Corrige le biais de survie des cartes lourdes (elles n'apparaissent que dans les longues parties).",
  score: "Score James-Stein : lisse le lift brut de ce matchup vers le lift global du leader. Plus mu est grand, moins le prior global influence le résultat.",
  pro: "PRO (Play-Rate in Opening) : % des parties où cette carte, présente en main de départ, a réellement été utilisée — déployée, jouée en counter, ou défaussée par un effet. Sépare les cartes actives des briques mortes : un bon winrate avec un PRO faible = corrélation trompeuse (la carte est portée par une main forte, elle ne cause pas la victoire). Vert ≥60%, orange ≥30%, rouge en dessous.",
  dead: "Dead-in-Hand WR : winrate des parties où tu avais cette carte en main de départ mais ne l'as JAMAIS utilisée. Si ce winrate reste élevé, l'impact de la carte est illusoire (la main gagnait sans elle). n = nombre de ces parties « morte en main ».",
  mu: "Parties observées dans ce matchup spécifique.",
  global: "Parties globales du leader, toutes adversaires confondues. Sert de prior dans le modèle.",
  garder: "Statistiquement corrélé à la victoire en main de départ. Recommandation : conserver cette carte.",
  mulligan: "Statistiquement corrélé à la défaite en main de départ. Recommandation : redemander une nouvelle main de 5 cartes.",
  premier: "Jouer en premier : on place le premier corps et reçoit 3 DON!! au tour 2. Le DON!! est la ressource d'action — on les attache aux cartes pour activer leurs effets ou augmenter l'attaque.",
  second: "Jouer en second : 4 DON!! au tour 2 et une pioche supplémentaire. Plus de ressources, mais l'adversaire frappe en premier.",
  confiance: "Haute = ≥15 parties, Moyenne = ≥5, Faible = <5. Sous 5 parties la reco est instable.",
  score_main: "Somme des scores shrinkage des 5 cartes de la main de départ. Positif = main statistiquement favorable selon le modèle.",
  early: "Tours 1–3 : établissement de la courbe bas coût. Les cartes ici définissent le rythme d'ouverture.",
  mid: "Tours 4–6 : développement du board et activation des synergies.",
  late: "Tours 7+ : cartes lourdes et résolution des parties longues.",
  premier_second: "Compare le winrate selon l'ordre de jeu. Premier (3 DON!! T2) favorise l'agressivité et la prise de tempo. Second (4 DON!! T2 + pioche bonus) donne plus de ressources et de réactivité. Un écart important révèle si le deck est conçu pour un ordre spécifique.",
  mulligan_split: "Compare le winrate quand la main initiale est gardée vs quand elle est mulligan (nouvelle main). Gardé > Mulligan : la main par défaut est favorable. Mulligan > Gardé : le deck est inconsistant ou la main initiale est faible. Attention : biais de sélection — un joueur expérimenté ne mulligan que les mauvaises mains.",
  par_deck: "Winrate par deck nommé que TU as joué (un même leader peut être plusieurs decks). Le deck est inféré en comparant les cartes jouées à tes decklists du jeu : decklist complète (ranked) ou cartes vues (parties directes). « deck non identifié » = trop peu de cartes ou aucune decklist correspondante. Cliquer ouvre la composition du deck.",
  matchups: "Winrate contre chaque adversaire rencontré. Classé par volume de parties. Cliquer ouvre la vue détaillée : reco mulligan spécifique, cartes clés, courbes de vie et DON!! pour ce matchup.",
  reco_mu: "Recommandation de mulligan spécifique à ce matchup. Basée sur la corrélation entre la présence d'une carte en main de départ et le résultat final. Distingue Premier et Second si assez de données sont disponibles. Voir 'confiance' pour estimer la fiabilité de la recommandation.",
  curve_life: "Évolution des Life cards restantes au fil des tours, séparée victoires/défaites. En One Piece TCG, chaque joueur commence avec 5 Life cards — les attaques adverses les retournent une par une. Atteindre 0 déclenche la défaite. Comparer les courbes révèle si les vies sont perdues trop vite ou si le jeu réussit à stabiliser.",
  curve_don: "Coût moyen des cartes déployées à chaque tour, séparé victoires/défaites. Révèle si le deck monte en puissance au bon rythme. Un coût plus élevé dans les victoires indique que jouer des cartes chères au bon moment est décisif. Un creux au milieu peut signaler un manque de cartes à coût intermédiaire.",
  lift_brut: "Lift brut = différence entre le winrate avec cette carte en main et le winrate de référence. Non lissé — sujet à variance sur petits échantillons (voir ±%).",
  lift_phase: "Le lift est comparé au winrate des parties ayant atteint le même tour, pas au winrate global. Corrige le biais de survie des cartes lourdes.",
  shrinkage: "Estimateur de James-Stein : lisse le lift brut du matchup vers le lift global du leader. Réduit les faux positifs au prix de faux négatifs sur cartes situationnelles (ex : cartes réactives).",
  pression: "% d'attaques dirigées vers le Leader adverse (retourner ses Life cards) vs vers son Board (éliminer ses cartes).",
  counters: "Un Counter est une carte défaussée depuis la main lors d'une attaque pour augmenter la puissance défensive. Stat : valeur totale et nombre de Counters joués par partie.",
  combos: "Paires de cartes déployées ensemble dans la même partie, corrélées à la victoire. Révèle des synergies invisibles dans les stats individuelles.",
  don_waste: "DON!! disponible mais non utilisé à la fin d'un tour. Un DON Waste élevé indique un under-utilisation des ressources — potentiellement des tours passifs ou un manque de cartes jouables au bon coût.",
  elo_gap: "Écart d'Elo entre les deux joueurs. Un écart positif = tu es favori. Compare le winrate selon que tu es favori ou underdog.",
  archetype: "Archétype prédit à partir des cartes publiques vues chez l'adversaire (leader + board + trash). Le modèle compare ces cartes aux decklists historiques pour inférer le deck adverse probable.",
  trigger_risk: "Probabilité que la prochaine Life card retournée soit un trigger. Calculée à partir des triggers encore non vus / cartes encore inconnues. Un % élevé signifie que l'adversaire a de bonnes chances de déclencher un effet gratuit en défense.",
  counter_analysis: "Analyse des counters +2000 : cartes déjà défaussées vs nombre attendu dans l'archétype. Si peu sont défaussées, l'adversaire en a probablement encore en main — attention aux clashes.",
  next_plays: "Menaces probables au prochain tour. Score = P(carte en main) × play-rate à la phase actuelle. Une carte à fort score est très probablement jouable ET sera probablement déployée ce tour.",
  lethal: "Évaluation du lethal : l'adversaire peut-il te tuer ce tour ? Puis-je tuer l'adversaire ? Basé sur la power totale, le nombre d'attaques, tes blockers et counters.",
  hand_score: "Score de la main de départ : somme des scores shrinkage des 5 cartes. Positif = main statistiquement favorable. Verdict : Garder (≥5), Mulligan (≤-5), Neutre entre les deux.",
  matchup_stats: "Winrate historique sur ce matchup précis (ton leader vs le leader adverse). n = nombre de parties enregistrées.",
  value_score: "Value Score : impact réel d'une carte à l'instant T, mesuré par State Diffing. Contrairement au Winrate/Lift qui mesurent le résultat final, le Value Score capture ce que la carte a réellement produit : cartes piochées (+2), perso adverse détruit (+cost), corps posé (+power/1000), vies infligées (+2), moins le DON investi (-cost). Un score positif = la carte génère plus de valeur qu'elle ne coûte.",
} as const;

export type StatsTipKey = keyof typeof STATS_TIPS;
