"use client";

import type { Archetype } from "@/lib/types";
import { CardImage } from "./Card";

export function ArchetypePanel({
  archetype,
  donEst,
}: {
  archetype?: Archetype;
  donEst?: number;
}) {
  if (!archetype)
    return (
      <section className="rounded-lg border border-slate-700 p-3">
        <h2 className="text-sm font-semibold">Archétype adverse</h2>
        <div className="text-slate-500 text-sm py-2">leader inconnu</div>
      </section>
    );

  const seen = new Set(archetype.revealed || []);
  const cards = [...(archetype.expected_cards || [])].sort((x, y) => {
    if (x.cost == null && y.cost == null) return 0;
    if (x.cost == null) return 1;
    if (y.cost == null) return -1;
    return x.cost - y.cost;
  });

  const donHtml = donEst != null ? `≤${donEst} Don ⬡` : "";

  return (
    <section className="rounded-lg border border-slate-700 p-3">
      <h2 className="mb-2 text-sm font-semibold">
        Archétype adverse — {archetype.leader_name}
        {archetype.leader_inferred && (
          <span className="ml-2 rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
            déduit
          </span>
        )}
        {donHtml && <span className="ml-2 text-xs text-green-400">{donHtml}</span>}
      </h2>
      <div className="flex gap-4 text-sm">
        <span><b>{archetype.n_historical}</b> decks vus</span>
        <span>recouvrement <b>{Math.round(archetype.nearest_overlap * 100)}%</b></span>
      </div>
      <div className="mt-2 text-xs uppercase tracking-wide text-slate-500">
        Deck probable (présence, trié par coût)
      </div>
      <div className="mt-1 space-y-1">
        {cards.length === 0 ? (
          <span className="text-slate-600">—</span>
        ) : (
          cards.map((c, i) => {
            const isSeen = seen.has(c.card_id);
            const playable =
              donEst != null &&
              c.cost != null &&
              c.cost <= donEst &&
              c.card_type !== "Leader";
            return (
              <div
                key={`${c.card_id}-${i}`}
                className={`flex items-center gap-2 rounded px-1 py-0.5 ${
                  isSeen ? "opacity-45" : ""
                } ${playable ? "bg-green-950/30" : ""}`}
              >
                {c.cost != null && (
                  <span
                    className={`w-6 text-center text-xs rounded ${
                      playable ? "bg-green-900 text-green-400" : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {c.cost}
                  </span>
                )}
                <CardImage id={c.card_id} name={c.name} />
                <span className="flex-1 truncate text-sm">{c.name}</span>
                <span className="text-xs text-slate-400">
                  {Math.round(c.presence)}% ~{c.avg_copies.toFixed(1)}x
                </span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
