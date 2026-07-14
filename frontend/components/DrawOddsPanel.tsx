"use client";

import type { DrawOdds } from "@/lib/types";
import { TooltipIcon } from "./Tooltip";

function pct(v: number): string {
  return `${v.toFixed(1)}%`;
}

export function DrawOddsPanel({
  odds,
  compact = false,
}: {
  odds: DrawOdds;
  /** Overlay : ligne trigger/counter + top 3 cartes, sans tableau. */
  compact?: boolean;
}) {
  const exact = odds.mode === "exact";
  if (compact) {
    const top = odds.per_card.slice(0, 3);
    return (
      <div>
        <div className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold">
          🃏 Pioche
          {exact && <span title="état exact (mod)">⚡</span>}
          {!exact && odds.reliable && odds.deck_name && (
            <span
              className="min-w-0 max-w-24 truncate font-normal text-green-400"
              title={`Deck identifié avec certitude : « ${odds.deck_name} » (toutes tes cartes vues n'existent que dans ce deck)`}
            >
              ✓ {odds.deck_name}
            </span>
          )}
          <span className="font-normal text-slate-400">
            Trigger {pct(odds.deck_level.trigger_next)} · Counter{" "}
            {pct(odds.deck_level.counter_next)}
          </span>
        </div>
        <div className="space-y-0.5">
          {top.map((c) => (
            <div key={c.card_id} className="flex items-center gap-1.5 text-[11px]">
              <span className="w-6 shrink-0 rounded bg-slate-700 px-1 text-center text-white">
                {c.copies}×
              </span>
              <span className="min-w-0 flex-1 truncate text-slate-200">{c.name}</span>
              <span className="h-1 w-10 shrink-0 overflow-hidden rounded bg-slate-800">
                <span
                  className="block h-full rounded bg-blue-500"
                  style={{ width: `${Math.min(100, c.p_next)}%` }}
                />
              </span>
              <span className="w-10 shrink-0 text-right tabular-nums text-slate-300">
                {pct(c.p_next)}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs">
        <span
          className={`rounded px-1.5 py-0.5 font-medium ${
            exact ? "bg-amber-600/30 text-amber-300" : "bg-slate-700 text-slate-300"
          }`}
        >
          {exact ? "⚡ état exact" : "approximatif"}
        </span>
        <span className="text-slate-500">
          Prochaine pioche depuis {odds.pool} cartes non vues
          {odds.deck_name ? ` · deck « ${odds.deck_name} »` : ""}
        </span>
        <TooltipIcon text="Loi hypergéométrique : probabilité de piocher au moins un exemplaire dès ta prochaine pioche, sachant les copies non encore vues réparties entre ton deck et tes vies. En mode 'approximatif', ta decklist est devinée par recoupement ; en 'état exact' (mod), elle est connue." />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <StatBox label="≥1 Trigger pioché" value={pct(odds.deck_level.trigger_next)} />
        <StatBox label="≥1 Counter pioché" value={pct(odds.deck_level.counter_next)} />
      </div>

      <div className="overflow-hidden rounded border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/60 text-xs text-slate-500">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Carte</th>
              <th className="px-2 py-1 text-right font-medium">Restantes</th>
              <th className="px-2 py-1 text-left font-medium">Proba</th>
              <th className="px-2 py-1 text-right font-medium tabular-nums">Prochaine pioche</th>
            </tr>
          </thead>
          <tbody>
            {odds.per_card.map((c) => (
              <tr key={c.card_id} className="border-t border-slate-800/60">
                <td className="px-2 py-1 text-slate-200">
                  {c.name} <span className="text-slate-500">({c.card_id})</span>
                </td>
                <td className="px-2 py-1 text-right">
                  <span className="rounded bg-slate-700 px-1 text-xs text-white">{c.copies}×</span>
                </td>
                <td className="px-2 py-1">
                  <div className="h-2 w-full rounded bg-slate-900">
                    <div
                      className="h-2 rounded bg-blue-600"
                      style={{ width: `${Math.min(100, c.p_next)}%` }}
                    />
                  </div>
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-300">{pct(c.p_next)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {odds.truncated && (
        <p className="text-xs text-slate-600">
          {odds.n_cards} cartes différentes restantes — seules les {odds.per_card.length} plus
          probables sont affichées.
        </p>
      )}
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-2 text-center">
      <div className="text-sm font-bold tabular-nums text-slate-200">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
