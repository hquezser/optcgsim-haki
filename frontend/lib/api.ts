// Client API pour communiquer avec le backend FastAPI (port 8765 par défaut).

import type { LiveState } from "./types";

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
