export interface MatchSummary {
  id: string;
  played_at: string | null;
  result: "win" | "loss";
  win_reason: string | null;
  mode: string | null;
  meta: string | null;
  my_leader: string | null;
  my_leader_name: string | null;
  opp_leader: string | null;
  opp_leader_name: string | null;
  duration_s: number | null;
  my_deck: string | null;
  went_first: number | null;
}

export interface MatchInfo {
  id: string;
  played_at: string | null;
  result: "win" | "loss";
  win_reason: string | null;
  my_leader: string | null;
  my_leader_name: string | null;
  opp_leader: string | null;
  opp_leader_name: string | null;
  duration_s: number | null;
  went_first: number | null;
}

export interface TurnSnapshot {
  turn: number;
  side: "me" | "opp";
  life: number | null;
  hand_count: number | null;
  deck_remaining: number | null;
}

export interface MatchEvent {
  turn: number;
  side: "me" | "opp";
  type: "deploy" | "attack" | "counter" | "counter_event";
  card_id: string | null;
  card_name: string | null;
  target_id: string | null;
  target_name: string | null;
}

export interface Highlight {
  turn: number;
  side: "me" | "opp";
  type: string;
  icon: string;
  label: string;
}

export interface ValueTurnEntry {
  turn: number;
  value: number;
  cumulative: number;
  deploys: { card_id: string; name: string; value: number }[];
}

export interface MatchTimeline {
  match: MatchInfo;
  snapshots: TurnSnapshot[];
  events: MatchEvent[];
  highlights: Highlight[];
  value_timeline: ValueTurnEntry[];
}
