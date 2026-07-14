"use client";

import type { OppSeenCard } from "@/lib/types";

/** Panneau « exemplaires adverses vus » (« 2/4 ») — 100 % public/exact, pensé pour l'overlay.
 *
 *  Pur comptage des cartes jouées depuis la main adverse (événements publics du log) :
 *  savoir que 3/4 counters events sont déjà passés est décisif pour attaquer. Aucune
 *  inférence — si ce n'est pas sorti de sa main, ce n'est pas compté.
 */
export function OppSeenPanel({ list, max = 6 }: { list: OppSeenCard[]; max?: number }) {
  if (!list?.length) return null;
  const shown = list.slice(0, max);
  const extra = list.length - shown.length;
  return (
    <section>
      <div className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold">
        👁 Vu chez ADV
        <span className="font-normal text-slate-500">exemplaires joués / 4</span>
      </div>
      <div className="space-y-0.5">
        {shown.map((c) => (
          <div key={c.card_id} className="flex items-center gap-1.5 text-[11px]">
            <span
              className={`w-8 shrink-0 rounded px-1 text-center tabular-nums ${
                c.count >= 4 ? "bg-green-900/60 text-green-300" : "bg-slate-700 text-slate-200"
              }`}
              title={c.count >= 4 ? "Playset épuisé : il n'en reste aucun" : undefined}
            >
              {c.count}/4
            </span>
            <span className="min-w-0 flex-1 truncate text-slate-200">
              {c.name || c.card_id}
            </span>
          </div>
        ))}
        {extra > 0 && (
          <div className="text-[10px] text-slate-500">+{extra} autres cartes vues</div>
        )}
      </div>
    </section>
  );
}
