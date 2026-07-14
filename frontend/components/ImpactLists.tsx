"use client";

import type { OpeningImpactCard, PlayedImpactCard, ScoredCard, WinningCombo } from "@/lib/stats-types";
import { CardImage } from "./Card";
import { Tooltip } from "./Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";

// CI à 95% sur un lift : 1.96 × √(p(1-p)/n) × 100
function ciMargin(wr: number, n: number): number {
  const p = wr / 100;
  return 1.96 * Math.sqrt((p * (1 - p)) / Math.max(1, n)) * 100;
}

export function OpeningImpactList({ cards, baseline }: { cards: OpeningImpactCard[]; baseline: number }) {
  if (!cards || cards.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  return (
    <div className="space-y-1">
      {cards.slice(0, 15).map((c, i) => {
        const ci = ciMargin(c.winrate, c.n);
        const ciCls = ci > 30 ? "text-red-400" : ci > 15 ? "text-amber-400" : "text-slate-500";
        const liftCls = c.lift > 5 ? "text-green-400" : c.lift < -5 ? "text-red-400" : "text-slate-400";
        return (
          <div key={i} className="flex items-center gap-2 py-1 border-b border-slate-800">
            <CardImage id={c.card_id} name={c.name} className="w-8 h-11" />
            <span className="flex-1 truncate text-sm text-slate-300">{c.name}</span>
            <span className={`text-sm tabular-nums ${liftCls}`}>
              {c.lift > 0 ? "+" : ""}{c.lift.toFixed(0)}%
            </span>
            <span className={`text-xs ${ciCls}`}><Tooltip label={`±${ci.toFixed(0)}%`} text={STATS_TIPS.ci} /></span>
            {c.pro != null && (
              <span className="text-xs text-slate-500">
                <Tooltip label={`PRO ${c.pro.toFixed(0)}%`} text={STATS_TIPS.pro} />
              </span>
            )}
            {c.dwr_dead != null && (
              <span className="text-xs text-slate-500">
                <Tooltip label={`Dead ${c.dwr_dead.toFixed(0)}%`} text={STATS_TIPS.dead} />
              </span>
            )}
            <span className="text-xs text-slate-600"><Tooltip label={`n=${c.n}`} text={STATS_TIPS.n} /></span>
          </div>
        );
      })}
    </div>
  );
}

export function PlayedImpactList({ cards }: { cards: PlayedImpactCard[] }) {
  if (!cards || cards.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  const phaseColor: Record<string, string> = {
    early: "bg-green-900/40 text-green-400",
    mid: "bg-amber-900/30 text-amber-400",
    late: "bg-slate-700 text-slate-400",
  };
  return (
    <div className="space-y-1">
      {cards.slice(0, 12).map((c, i) => (
        <div key={i} className="flex items-center gap-2 py-1 border-b border-slate-800">
          <CardImage id={c.card_id} name={c.name} className="w-8 h-11" />
          <span className="flex-1 truncate text-sm text-slate-300">{c.name}</span>
          <span className={`rounded px-1.5 text-xs ${phaseColor[c.phase]}`}>
            <Tooltip label={`${c.phase} T${c.mode_turn}`} text={STATS_TIPS.mode_turn} />
          </span>
          <span className={`text-sm tabular-nums ${c.lift > 5 ? "text-green-400" : c.lift < -5 ? "text-red-400" : "text-slate-400"}`}>
            {c.lift > 0 ? "+" : ""}{c.lift.toFixed(0)}%
          </span>
          <span className="text-xs text-slate-500">
            <Tooltip label={`base ${c.cond_baseline}%`} text={STATS_TIPS.baseline} />
          </span>
          <span className="text-xs text-slate-600"><Tooltip label={`n=${c.n}`} text={STATS_TIPS.n} /></span>
        </div>
      ))}
    </div>
  );
}

export function ShrinkageList({ scored }: { scored: ScoredCard[] }) {
  if (!scored || scored.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  return (
    <div className="space-y-1">
      {scored.slice(0, 12).map((c, i) => (
        <div key={i} className="flex items-center gap-2 py-1 border-b border-slate-800">
          <CardImage id={c.card_id} name={c.name} className="w-8 h-11" />
          <span className="flex-1 truncate text-sm text-slate-300">{c.name}</span>
          <span className={`text-sm tabular-nums font-semibold ${c.score > 5 ? "text-green-400" : c.score < -5 ? "text-red-400" : "text-slate-400"}`}>
            {c.score > 0 ? "+" : ""}{c.score.toFixed(1)}
          </span>
          {c.pro != null && (
            <span className="text-xs text-slate-500">
              <Tooltip label={`PRO ${c.pro.toFixed(0)}%`} text={STATS_TIPS.pro} />
            </span>
          )}
          <span className="text-xs text-slate-600"><Tooltip label={`n=${c.n_overall}`} text={STATS_TIPS.n} /></span>
        </div>
      ))}
    </div>
  );
}

export function CombosList({ combos }: { combos: WinningCombo[] }) {
  if (!combos || combos.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  return (
    <div className="space-y-1">
      {combos.slice(0, 8).map((c, i) => (
        <div key={i} className="flex items-center gap-2 py-1 border-b border-slate-800 rounded bg-slate-900/40 px-2">
          <CardImage id={c.a_id} name={c.a_name} className="w-8 h-11" />
          <span className="text-slate-500">+</span>
          <CardImage id={c.b_id} name={c.b_name} className="w-8 h-11" />
          <span className="flex-1 truncate text-sm text-slate-300">{c.a_name} + {c.b_name}</span>
          <span className={`text-sm tabular-nums ${c.lift > 5 ? "text-green-400" : c.lift < -5 ? "text-red-400" : "text-slate-400"}`}>
            {c.lift > 0 ? "+" : ""}{c.lift.toFixed(0)}%
          </span>
          <span className="text-xs text-slate-600">n={c.n}</span>
        </div>
      ))}
    </div>
  );
}
