"use client";

import { cardImgUrl } from "@/lib/api";
import type { CardRef } from "@/lib/types";

export function CardImage({
  id,
  name,
  size = "small",
  className = "",
}: {
  id: string;
  name: string | null | undefined;
  size?: "small" | "full";
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={cardImgUrl(id, size)}
      alt={name || id}
      title={name || id}
      loading="lazy"
      className={`rounded border border-slate-700 bg-slate-900 object-cover transition-transform hover:scale-2.4 hover:z-60 hover:relative ${className}`}
      onError={(e) => {
        const t = e.target as HTMLImageElement;
        t.outerHTML = `<span class="inline-flex items-center justify-center rounded bg-slate-800 px-2 py-1 text-xs text-slate-400">${name || id}</span>`;
      }}
    />
  );
}

export function CardChips({
  cards,
  seen,
}: {
  cards: CardRef[];
  seen?: Set<string>;
}) {
  if (!cards || cards.length === 0)
    return <span className="text-slate-600">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {cards.map((c, i) => (
        <span
          key={`${c.id ?? "?"}-${i}`}
          className={c.id && seen?.has(c.id) ? "opacity-50" : ""}
        >
          {c.id ? (
            <CardImage id={c.id} name={c.name} />
          ) : (
            // Carte inconnue (reveal-all approximatif : identité non révélée par le log).
            <span className="inline-flex h-[3.5rem] w-10 items-center justify-center rounded border border-dashed border-slate-600 text-slate-500" title="Carte inconnue (effet de main non tracé)">?</span>
          )}
        </span>
      ))}
    </div>
  );
}

export function GroupedCards({ cards }: { cards: CardRef[] }) {
  if (!cards || cards.length === 0)
    return <span className="text-slate-600">—</span>;
  const cnt: Record<string, number> = {};
  const nm: Record<string, string> = {};
  cards.forEach((c) => {
    if (!c.id) return; // placeholder "?" (reveal-all) : pas de regroupement
    cnt[c.id] = (cnt[c.id] || 0) + 1;
    nm[c.id] = c.name;
  });
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(cnt)
        .sort((a, b) => b[1] - a[1])
        .map(([id, n]) => (
          <span key={id} className="relative">
            {n > 1 && (
              <span className="absolute -top-1 -right-1 z-10 rounded bg-slate-700 px-1 text-xs text-white">
                {n}×
              </span>
            )}
            <CardImage id={id} name={nm[id]} />
          </span>
        ))}
    </div>
  );
}
