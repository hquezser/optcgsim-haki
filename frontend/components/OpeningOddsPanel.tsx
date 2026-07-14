"use client";

import type { DeckDetail } from "@/lib/stats-types";
import { TooltipIcon } from "./Tooltip";

type Odds = DeckDetail["odds"];

function pct(v: number): string {
  return `${v.toFixed(1)}%`;
}

export function OpeningOddsPanel({ odds }: { odds: Odds }) {
  const dl = odds.deck_level;
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Loi hypergéométrique (tirage sans remise) sur une main de {odds.hand_size} cartes
        depuis un deck de {odds.deck_size} cartes connues.
        <TooltipIcon text="Loi hypergéométrique : probabilité de tirer au moins une copie d'une carte sachant qu'on pioche sans remise. Le mulligan (rendre toute la main et repiocher 5) double la chance : P = 1 − (1 − p)²." />
      </p>

      <div className="grid grid-cols-3 gap-2">
        <StatBox label="≥1 Trigger en main" value={pct(dl.trigger_in_hand)} />
        <StatBox label="≥1 Trigger en vies" value={pct(dl.trigger_in_life)} />
        <StatBox label="≥1 Counter en main" value={pct(dl.counter_in_hand)} />
      </div>

      <div className="overflow-hidden rounded border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/60 text-xs text-slate-500">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Carte</th>
              <th className="px-2 py-1 text-right font-medium">Copies</th>
              <th className="px-2 py-1 text-left font-medium">Proba (main)</th>
              <th className="px-2 py-1 text-right font-medium tabular-nums">Main</th>
              <th className="px-2 py-1 text-right font-medium tabular-nums">Mulligan</th>
            </tr>
          </thead>
          <tbody>
            {odds.per_card.map((c) => (
              <tr key={c.card_id} className="border-t border-slate-800/60">
                <td className="px-2 py-1 text-slate-200">
                  {c.name} <span className="text-slate-500">({c.card_id})</span>
                </td>
                <td className="px-2 py-1 text-right">
                  <span className="rounded bg-slate-700 px-1 text-xs text-white">{c.qty}×</span>
                </td>
                <td className="px-2 py-1">
                  <div className="h-2 w-full rounded bg-slate-900">
                    <div
                      className="h-2 rounded bg-blue-600"
                      style={{ width: `${Math.min(100, c.p_opening)}%` }}
                    />
                  </div>
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-300">
                  {pct(c.p_opening)}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-400">
                  {pct(c.p_mulligan)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
