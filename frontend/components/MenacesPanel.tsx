"use client";

import type { NextPlay } from "@/lib/types";
import { CardImage } from "./Card";

const PHASE_LABELS: Record<string, string> = {
  early: "Early T1-3",
  mid: "Mid T4-6",
  late: "Late T7+",
};

const PHASE_COLORS: Record<string, string> = {
  early: "text-green-400",
  mid: "text-yellow-400",
  late: "text-red-400",
};

export function MenacesPanel({
  list,
  donEst,
  phase,
  turn,
  compact = false,
}: {
  list?: NextPlay[];
  donEst?: number;
  phase?: string;
  turn?: number | null;
  /** Overlay : top 3 en une ligne par carte (nom · coût · %), sans images. */
  compact?: boolean;
}) {
  const sub = donEst != null ? `≤${donEst} Don ⬡ au T+1` : "";
  const phaseLabel = phase ? PHASE_LABELS[phase] : null;
  const phaseColor = phase ? PHASE_COLORS[phase] : "";

  if (compact) {
    const top = (list ?? []).slice(0, 3);
    if (top.length === 0) return null;
    return (
      <section>
        <h2 className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold">
          🎯 Menaces T+1
          {donEst != null && <span className="font-normal text-green-400">≤{donEst}⬡</span>}
          {phaseLabel && (
            <span className={`font-normal ${phaseColor}`}>
              {phaseLabel}
              {turn != null && ` · T${turn}`}
            </span>
          )}
        </h2>
        <div className="space-y-0.5">
          {top.map((t, i) => (
            <div
              key={`${t.card_id}-${i}`}
              className="flex items-center gap-1.5 text-[11px]"
              title={`${t.name || t.card_id || ""} — ${t.prob}% probable, coût ${t.cost}`}
            >
              <span className="w-7 shrink-0 rounded bg-slate-700 px-1 text-center text-blue-300">
                {t.cost}⬡
              </span>
              <span className="min-w-0 flex-1 truncate text-slate-200">
                {t.name || t.card_id}
              </span>
              <span className="h-1 w-10 shrink-0 overflow-hidden rounded bg-slate-800">
                <span
                  className="block h-full rounded bg-orange-500"
                  style={{ width: `${Math.min(100, t.prob)}%` }}
                />
              </span>
              <span className="w-8 shrink-0 text-right tabular-nums text-orange-400">
                {t.prob}%
              </span>
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (!list || list.length === 0)
    return (
      <section className="rounded-lg border border-slate-700 p-3">
        <h2 className="text-sm font-semibold">
          🎯 Menaces probables
          {sub && <span className="ml-2 text-xs text-green-400">{sub}</span>}
        </h2>
        <div className="text-slate-500 text-sm py-2">
          Pas encore de prédiction (leader/cartes adverses insuffisants).
        </div>
      </section>
    );

  return (
    <section className="rounded-lg border border-slate-700 p-3">
      <h2 className="mb-2 text-sm font-semibold">
        🎯 Menaces probables (T+1)
        {sub && <span className="ml-2 text-xs text-green-400">{sub}</span>}
        {phaseLabel && (
          <span className={`ml-2 text-xs ${phaseColor}`}>
            {phaseLabel}
            {turn != null && ` · T${turn}`}
          </span>
        )}
      </h2>
      <div className="flex flex-wrap gap-2">
        {list.map((t, i) => {
          const hasAdjust = t.raw_prob != null && t.play_rate != null;
          const tooltip = hasAdjust
            ? `${t.name || ""} — ${t.prob}% (présence ${t.raw_prob}% × play-rate ${t.play_rate}%), coût ${t.cost}`
            : `${t.name || ""} — ${t.prob}% probable, coût ${t.cost}`;
          return (
            <span
              key={`${t.card_id}-${i}`}
              className="inline-flex flex-col items-center"
              title={tooltip}
            >
              <CardImage id={t.card_id} name={t.name} />
              <span className="mt-0.5 flex items-center gap-1">
                <span className="rounded bg-orange-900/40 px-1 text-xs text-orange-400">
                  {t.prob}%
                </span>
                <span className="rounded bg-slate-700 px-1 text-xs text-blue-300">
                  {t.cost}⬡
                </span>
              </span>
              {hasAdjust && t.raw_prob! > t.prob && (
                <span className="text-[10px] text-slate-500" title={`Présence brute ${t.raw_prob}% → pondérée ${t.prob}% (play-rate ${t.play_rate}% en ${phaseLabel})`}>
                  ↓{t.raw_prob}%
                </span>
              )}
            </span>
          );
        })}
      </div>
      {phaseLabel && (
        <p className="mt-2 text-[11px] text-slate-500">
          Score pondéré par le play-rate réel en {phaseLabel}.
        </p>
      )}
    </section>
  );
}
