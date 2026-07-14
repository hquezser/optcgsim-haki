"use client";

import type { ValueScoreCard } from "@/lib/stats-types";
import { CardImage } from "./Card";

export function ValueScorePanel({ cards }: { cards: ValueScoreCard[] }) {
  if (!cards || cards.length === 0) {
    return <p className="text-slate-500 text-sm">Pas assez de données (nécéssite des events deploy + KO/dégâts parsés).</p>;
  }

  const top = cards.slice(0, 15);
  const maxAbs = Math.max(...top.map((c) => Math.abs(c.avg_value)), 1);

  return (
    <div className="space-y-1">
      {top.map((c, i) => {
        const pct = Math.min(100, (Math.abs(c.avg_value) / maxAbs) * 100);
        const isPositive = c.avg_value >= 0;
        const barCls = isPositive ? "bg-green-600" : "bg-red-600";
        const valCls = isPositive ? "text-green-400" : "text-red-400";
        const winLossGap = c.avg_value_win != null && c.avg_value_loss != null
          ? c.avg_value_win - c.avg_value_loss
          : null;
        // IC 95 % : effet non significatif si l'intervalle traverse 0 -> on l'atténue.
        const notSignificant = c.significant === false && c.ci_low != null && c.ci_high != null;
        const ciTitle = c.ci_low != null && c.ci_high != null
          ? `IC 95 % : [${c.ci_low.toFixed(1)} ; ${c.ci_high.toFixed(1)}]${notSignificant ? " — traverse 0, non significatif" : ""}`
          : "Échantillon trop faible pour un intervalle de confiance";
        return (
          <div key={i} className="flex items-center gap-2 py-1 border-b border-slate-800">
            <CardImage id={c.card_id} name={c.name} className="w-8 h-11" />
            <span className="flex-1 truncate text-sm text-slate-300">{c.name}</span>
            {c.avg_cost != null && (
              <span className="text-xs text-slate-500 tabular-nums">{c.avg_cost}D</span>
            )}
            {c.vpd != null && (
              <span className={`text-xs tabular-nums ${c.vpd >= 0 ? "text-blue-400" : "text-red-500"}`}>
                VPD {c.vpd > 0 ? "+" : ""}{c.vpd}
              </span>
            )}
            {c.avg_early_value != null && c.avg_early_value !== 0 && (
              <span className={`text-xs tabular-nums ${c.avg_early_value > 0 ? "text-cyan-400" : "text-slate-600"}`}>
                EV {c.avg_early_value > 0 ? "+" : ""}{c.avg_early_value}
              </span>
            )}
            <span className="w-24 rounded bg-slate-900 h-3.5 overflow-hidden">
              <span className={`block h-full ${barCls} ${notSignificant ? "opacity-40" : ""}`} style={{ width: `${pct}%` }} />
            </span>
            <span
              className={`w-12 text-right text-sm tabular-nums font-semibold ${valCls} ${notSignificant ? "opacity-50 italic" : ""}`}
              title={ciTitle}
            >
              {c.avg_value > 0 ? "+" : ""}{c.avg_value.toFixed(1)}
            </span>
            {notSignificant && (
              <span className="text-[10px] text-slate-600 uppercase" title={ciTitle}>n.s.</span>
            )}
            {winLossGap != null && (
              <span className={`w-10 text-right text-xs tabular-nums ${winLossGap > 0 ? "text-green-500" : "text-slate-500"}`}>
                Δ{winLossGap > 0 ? "+" : ""}{winLossGap.toFixed(1)}
              </span>
            )}
            <span className="text-xs text-slate-600 tabular-nums">n={c.n}</span>
          </div>
        );
      })}
      <p className="mt-2 text-xs text-slate-500">
        Value = +2/carte piochée · +cost/perso détruit · +power/1000 corps posé · +2/vie infligée · -cost/DON investi.
        VPD = Value Per DON (efficacité). EV = Early Value (T1-T4). « n.s. » = intervalle de
        confiance 95 % traversant 0 (effet non significatif, survolez la valeur pour l'IC).
      </p>
    </div>
  );
}
