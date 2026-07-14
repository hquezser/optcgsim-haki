// Types pour les réponses de l'API /api/stats et /api/decks.

export interface StatsRow {
  label: string;
  wins: number;
  losses: number;
  total: number;
  winrate: number;
}

export interface MatchupRow {
  opp_id: string;
  name: string;
  wins: number;
  losses: number;
  winrate: number;
}

export interface OpeningImpactCard {
  card_id: string;
  name: string;
  n: number;
  winrate: number;
  lift: number;
  pro: number | null;
  n_used: number;
  dwr_dead: number | null;
  n_dead: number;
}

export interface PlayedImpactCard {
  card_id: string;
  name: string;
  n: number;
  winrate: number;
  lift: number;
  mode_turn: number;
  phase: "early" | "mid" | "late";
  cond_baseline: number;
  cond_n: number;
}

export interface WinningCombo {
  a_id: string;
  a_name: string;
  b_id: string;
  b_name: string;
  n: number;
  winrate: number;
  lift: number;
}

export interface ScoredCard {
  card_id: string;
  name: string;
  score: number;
  n: number;
  n_overall: number;
  pro: number | null;
  dwr_dead: number | null;
  n_dead: number;
  avg_early_value: number | null;
}

export interface MulliganReco {
  keep: ScoredCard[];
  avoid: ScoredCard[];
  premier: { keep: ScoredCard[]; avoid: ScoredCard[] };
  second: { keep: ScoredCard[]; avoid: ScoredCard[] };
  scored: ScoredCard[];
  confidence: string;
}

export interface HandScoreStats {
  avg_win: number;
  avg_loss: number;
  n_win: number;
  n_loss: number;
}

export interface CurveData {
  win: [number, number][];
  loss: [number, number][];
  n_win: number;
  n_loss: number;
}

export interface AttackDist {
  win: { life_pct: number; n: number };
  loss: { life_pct: number; n: number };
  n_win: number;
  n_loss: number;
}

export interface CounterStats {
  win: { avg_value: number; avg_count: number };
  loss: { avg_value: number; avg_count: number };
  n_win: number;
  n_loss: number;
}

export interface DonWasteSummary {
  avg_total: number;
  avg_per_turn: number;
  n: number;
}

export interface DonWasteData {
  curve: CurveData;
  summary: {
    win: DonWasteSummary;
    loss: DonWasteSummary;
  };
  n_win: number;
  n_loss: number;
}

export interface ValueScoreCard {
  card_id: string;
  name: string;
  n: number;
  avg_value: number;
  avg_value_win: number | null;
  avg_value_loss: number | null;
  avg_cost: number | null;
  avg_early_value: number;
  vpd: number | null;
  ci_low: number | null;
  ci_high: number | null;
  significant: boolean;
}

// Réponses API complètes
export interface StatsMetasResponse {
  level: "metas";
  metas: StatsRow[];
  features?: Record<string, boolean>;
}

export interface StatsMetaResponse {
  level: "meta";
  meta: string;
  leaders: StatsRow[];
  decks: StatsRow[];
  features?: Record<string, boolean>;
}

export interface StatsDetailResponse {
  level: "detail";
  meta: string;
  leader_id: string | null;
  label: string;
  deck: string | null;
  matchups: MatchupRow[];
  splits: {
    first_second: StatsRow[];
    mulligan: StatsRow[];
    elo_gap: StatsRow[];
  };
  opening_impact: {
    baseline_wr: number | null;
    n: number;
    cards: OpeningImpactCard[];
  };
  played_impact: PlayedImpactCard[];
  winning_combos: WinningCombo[];
  life_trajectory: CurveData | null;
  deploy_curve: CurveData | null;
  attack_distribution: AttackDist | null;
  counter_stats: CounterStats | null;
  don_waste: DonWasteData | null;
  value_scores?: ValueScoreCard[];
  features?: Record<string, boolean>;
}

export interface StatsMatchupResponse {
  level: "matchup";
  meta: string;
  leader_id: string | null;
  label: string;
  opp_id: string;
  opp_name: string;
  deck: string | null;
  head: string;
  matchup: MatchupRow | null;
  splits: {
    first_second: StatsRow[];
    elo_gap: StatsRow[];
  };
  mulligan_reco: MulliganReco;
  hand_score_stats: HandScoreStats | null;
  played_impact: PlayedImpactCard[];
  life_trajectory: CurveData | null;
  deploy_curve: CurveData | null;
  attack_distribution: AttackDist | null;
  counter_stats: CounterStats | null;
  don_waste: DonWasteData | null;
  features?: Record<string, boolean>;
}

export type StatsResponse =
  | StatsMetasResponse
  | StatsMetaResponse
  | StatsDetailResponse
  | StatsMatchupResponse;

export interface DeckSummary {
  name: string;
  leader?: string;
  leader_name?: string;
  total?: number;
  counter_1000?: number;
  counter_2000?: number;
  error?: boolean;
}

export interface DeckDetail {
  name: string;
  leader: string;
  leader_name: string;
  stats: {
    total: number;
    curve: Record<number, number>;
    counters: Record<number, number>;
    counter_total: number;
    counter_1000: number;
    counter_2000: number;
    colors: Record<string, number>;
    types: Record<string, number>;
    subtypes: Record<string, number>;
    power: Record<number, number>;
    rarities: Record<string, number>;
    attributes: Record<string, number>;
    effect_keys: Record<string, number>;
    effects_total: number;
    triggers_total: number;
    unknown: string[];
  };
  cards: { card_id: string; qty: number; name: string }[];
  odds: {
    deck_size: number;
    hand_size: number;
    per_card: { card_id: string; name: string; qty: number; p_opening: number; p_mulligan: number }[];
    deck_level: {
      trigger_in_hand: number;
      trigger_in_life: number;
      counter_in_hand: number;
      life_size: number;
    };
  };
}

export interface MetaCheckCard {
  card_id: string;
  name: string;
  cost: number | null;
  card_type: string | null;
  presence?: number;
  avg_copies?: number;
  lift?: number;
  n?: number;
  winrate?: number;
}

export interface MetaCheckResponse {
  deck_name: string;
  leader: string;
  leader_name: string;
  n_historical: number;
  staples_missing: MetaCheckCard[];
  staples_present: MetaCheckCard[];
  extra_cards: MetaCheckCard[];
  underperforming: MetaCheckCard[];
  top_performers: MetaCheckCard[];
}
