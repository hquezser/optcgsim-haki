"use client";

import type { OppKnownCard } from "@/lib/types";

/** Panneau « Connu en main ADV » — 100 % public/exact, pensé pour l'overlay.
 *
 *  Cartes dont l'adversaire a rendu l'identité publique en les tutorisant/révélant vers sa
 *  main (« Reveal and Draw »), et qui n'en sont pas encore reparties. C'est une borne BASSE
 *  exacte de sa main (au moins ces cartes-là), utile pour anticiper ses counters/réponses.
 *  Ne montre jamais la main cachée reconstruite — uniquement ce que le jeu a révélé.
 */
export function OppKnownHandPanel({ list, max = 6 }: { list: OppKnownCard[]; max?: number }) {
  if (!list?.length) return null;
  const shown = list.slice(0, max);
  const extra = list.length - shown.length;
  return (
    <section>
      <div className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold">
        🔎 Connu en main ADV
        <span className="font-normal text-slate-500">révélé publiquement</span>
      </div>
      <div className="space-y-0.5">
        {shown.map((c) => (
          <div key={c.card_id} className="flex items-center gap-1.5 text-[11px]">
            {c.count > 1 && (
              <span className="w-6 shrink-0 rounded bg-slate-700 px-1 text-center tabular-nums text-white">
                {c.count}×
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-slate-200">{c.name || c.card_id}</span>
          </div>
        ))}
        {extra > 0 && <div className="text-[10px] text-slate-500">+{extra} autres</div>}
      </div>
    </section>
  );
}
