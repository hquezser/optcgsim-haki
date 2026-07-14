// Types TypeScript du payload /api/state (mirror du Python LiveState._state_payload).

export interface CardRef {
  id: string | null; // null = carte inconnue (placeholder "?")
  name: string;
}

export interface PlayerState {
  tag: string;
  side: "me" | "opp";
  leader: string | null;
  leader_name: string | null;
  life: number | null;
  deck_remaining: number | null;
  don_on_field: number | null;
  board: CardRef[];
  trash: CardRef[];
  hand_count: number | null;
  hand_count_approx: boolean;
  hand: CardRef[] | null; // null = cachée (fair-play)
  hand_approx?: boolean;  // main reconstruite (reveal-all) : best-effort, dérive sur effets
  // Counters dépensés ("Discard ... for Counter N") : événement public, comptage exact.
  counters_spent?: { count: number; total: number };
  // true = leader déduit des cartes vues (jamais loggé en live), pas observé directement.
  leader_inferred?: boolean;
}

/** Panneau défense : inputs exacts (mes snapshots) + publics (board adverse visible).
 *  Disponible dès le tour 0 (le leader adverse n'est pas requis). Les champs de simulation
 *  (lives_at_risk, opp_can_lethal) n'existent que quand les deux leaders sont connus.
 *  Caveat structurel : ne compte pas les menaces cachées en main adverse (rush/buff). */
export interface DefenseState {
  my_life: number | null;
  my_blockers: number;
  my_counter_pool: number;
  opp_attacks: number | null;
  opp_power: number | null;
  opp_don: number;
  opp_leader_known: boolean;  // false = leader adverse pas encore compté dans opp_power
  lives_at_risk?: number;
  opp_can_lethal?: boolean;
}

export interface ExpectedCard {
  card_id: string;
  name: string;
  presence: number;
  avg_copies: number;
  cost: number | null;
  card_type: string | null;
}

export interface Archetype {
  leader_name: string;
  leader_inferred: boolean;
  n_historical: number;
  nearest_overlap: number;
  expected_cards: ExpectedCard[];
  revealed: string[];
}

export interface CounterAnalysis {
  plus2k_in_trash: number;
  plus2k_expected: number | null;
  avg_counter: number | null;
}

export interface TriggerRisk {
  pct: number;
  remaining: number;
  total_expected: number;
  revealed: number;
  unknown: number;
}

export interface NextPlay {
  card_id: string;
  name: string;
  cost: number;
  prob: number;
  raw_prob?: number | null;
  play_rate?: number | null;
}

export interface HandScore {
  score: number;
  verdict: "Garder" | "Mulligan" | "Neutre";
}

export interface MatchupStats {
  wr: number | null;
  wins: number;
  n: number;
}

export interface RecentMatch {
  result: "win" | "loss";
  opp_leader: string;
  opp_name: string;
}

export interface AttackPlanStep {
  attacker_power: number;
  target_power: number;
  don_attached: number;
  final_power: number;
  role: string;  // "life" | "blocker" | "coup_de_grace"
}

export interface LethalConfidence {
  level: "high" | "medium" | "low";
  factors: string[];
  counter_threshold?: number | null;
}

export interface Lethal {
  opp_can_lethal: boolean;
  opp_power: number | null;
  opp_attacks: number | null;
  lives_at_risk: number;
  my_life: number | null;
  my_blockers: number;
  my_counter_pool: number;
  me_can_lethal: boolean;
  me_power: number | null;
  me_attacks: number | null;
  lives_i_can_deal: number;
  opp_life: number | null;
  opp_blockers: number;
  opp_counter_est: number;
  // --- Solveur : probabilité + plan d'attaque ---
  me_lethal_prob: number | null;       // % de lethal (intégrant le risque trigger)
  me_counter_threshold: number | null; // lethal tient si counters adverses ≤ ce seuil
  me_lethal_confidence: LethalConfidence | null;
  opp_lethal_confidence: LethalConfidence | null;
  me_don_available: number;
  me_don_needed: number | null;
  me_attack_plan: AttackPlanStep[];
  me_lethal_reason: string | null;
  opp_don_available: number;
  opp_don_needed: number | null;
  opp_attack_plan: AttackPlanStep[];
  opp_lethal_reason: string | null;
  trigger_risk_pct: number | null;
}

export interface LiveState {
  active: boolean;
  room_code: string | null;
  version: string | null;
  result: string | null;
  win_reason: string | null;
  reveal_all: boolean;
  is_solo?: boolean;      // true = Solo vs Self (les deux joueurs sont locaux)
  exact_state?: boolean;  // true = état servi par le mod BepInEx (exact), pas le log (inféré)
  me: PlayerState | null;
  opp: PlayerState | null;
  archetype?: Archetype;
  opp_don_est?: number;
  me_don_est?: number;
  counter_analysis?: CounterAnalysis;
  trigger_risk?: TriggerRisk;
  next_plays?: NextPlay[];
  next_plays_phase?: string;
  next_plays_turn?: number | null;
  hand_score?: HandScore;
  matchup_stats?: MatchupStats;
  recent_matches?: RecentMatch[];
  lethal?: Lethal;
  defense?: DefenseState;
  draw_odds?: DrawOdds;
  features?: Record<string, boolean>;
}

export interface DrawOddsCard {
  card_id: string;
  name: string;
  copies: number;
  p_next: number;   // % de piocher >=1 exemplaire dès la prochaine pioche
}

export interface DrawOdds {
  pool: number;           // taille de l'échantillon non vu (deck + vies en mode approx)
  n_cards: number;
  truncated: boolean;
  per_card: DrawOddsCard[];
  deck_level: { trigger_next: number; counter_next: number };
  mode: "approx" | "exact";
  deck_name?: string;     // nom du deck rapproché (mode approx)
  // true = fiable : decklist connue (exact) ou identifiée STRICTEMENT (toutes mes cartes
  // vues ⊆ un unique deck sauvegardé). Seules les odds fiables passent le profil v1.
  reliable?: boolean;
}
