// Client API pour communiquer avec le backend FastAPI (port 8765 par défaut).

import type { LiveState } from "./types";
import type { StatsResponse, DeckSummary, DeckDetail, MetaCheckResponse } from "./stats-types";
import type { MatchSummary, MatchTimeline } from "./match-types";

// Servi par l'API elle-même (build statique embarqué) : même origine ("") — suit --port.
// En dev (next dev sur :3000), l'API tourne ailleurs -> défaut 8765. NEXT_PUBLIC_API_BASE
// reste l'override explicite.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE
  || (typeof window !== "undefined" && window.location.port !== "3000"
      ? "" : "http://127.0.0.1:8765");

export async function fetchState(): Promise<LiveState | null> {
  try {
    const r = await fetch(`${API_BASE}/api/state`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function toggleReveal(on?: boolean): Promise<boolean | null> {
  try {
    const q = on === undefined ? "" : `?on=${on}`;
    const r = await fetch(`${API_BASE}/api/reveal${q}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()).reveal_all;
  } catch {
    return null;
  }
}

export function cardImgUrl(id: string, size: "small" | "full" = "small"): string {
  return `${API_BASE}/api/card?id=${encodeURIComponent(id)}&size=${size}`;
}

export async function fetchStats(params: Record<string, string | undefined>): Promise<StatsResponse | null> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  try {
    const r = await fetch(`${API_BASE}/api/stats?${qs}`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function fetchStatsFilters(): Promise<{ modes: string[]; formats: string[] } | null> {
  try {
    const r = await fetch(`${API_BASE}/api/stats/filters`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function fetchDecks(): Promise<DeckSummary[]> {
  try {
    const r = await fetch(`${API_BASE}/api/decks`, { cache: "no-store" });
    if (!r.ok) return [];
    const d = await r.json();
    return d.decks;
  } catch {
    return [];
  }
}

export async function fetchDeckDetail(name: string): Promise<DeckDetail | null> {
  try {
    const r = await fetch(`${API_BASE}/api/decks/${encodeURIComponent(name)}`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function fetchMetaCheck(name: string): Promise<MetaCheckResponse | null> {
  try {
    const r = await fetch(`${API_BASE}/api/decks/${encodeURIComponent(name)}/meta-check`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function fetchMatches(limit: number = 20): Promise<MatchSummary[]> {
  try {
    const r = await fetch(`${API_BASE}/api/matches?limit=${limit}`, { cache: "no-store" });
    if (!r.ok) return [];
    return r.json();
  } catch {
    return [];
  }
}

export async function fetchMatchTimeline(matchId: string): Promise<MatchTimeline | null> {
  try {
    const r = await fetch(`${API_BASE}/api/matches/${encodeURIComponent(matchId)}/timeline`, { cache: "no-store" });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}
