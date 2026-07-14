"use client";

import type { MulliganReco, HandScoreStats } from "@/lib/stats-types";
import { CardImage } from "./Card";
import { Tooltip, TooltipIcon } from "./Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";

export function MulliganRecoDisplay({ reco }: { reco: MulliganReco }) {
  const confCls =
    reco.confidence === "élevée"
      ? "text-green-400"
      : reco.confidence === "moyenne"
      ? "text-amber-400"
      : "text-slate-500";

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500">
        <Tooltip label="Confiance" text={STATS_TIPS.confiance} /> : <span className={confCls}>{reco.confidence}</span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h3 className="mb-1 text-sm font-semibold text-green-400">
            ✅ Garder<TooltipIcon text={STATS_TIPS.garder} />
          </h3>
          {reco.keep.length === 0 ? (
            <p className="text-slate-500 text-sm">—</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {reco.keep.map((c, i) => (
                <span key={i} className="relative" title={`${c.name} — score ${c.score.toFixed(1)}${c.avg_early_value != null ? ` · EV ${c.avg_early_value > 0 ? "+" : ""}${c.avg_early_value}` : ""}`}>
                  <span className="absolute -top-1 -right-1 z-10 rounded bg-green-900 px-1 text-xs text-green-400">
                    +{c.score.toFixed(0)}
                  </span>
                  {c.avg_early_value != null && c.avg_early_value > 0 && (
                    <span className="absolute -bottom-1 -left-1 z-10 rounded bg-cyan-900 px-0.5 text-[10px] text-cyan-400">
                      EV{c.avg_early_value.toFixed(0)}
                    </span>
                  )}
                  <CardImage id={c.card_id} name={c.name} />
                </span>
              ))}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-1 text-sm font-semibold text-red-400">
            ❌ Éviter<TooltipIcon text={STATS_TIPS.mulligan} />
          </h3>
          {reco.avoid.length === 0 ? (
            <p className="text-slate-500 text-sm">—</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {reco.avoid.map((c, i) => (
                <span key={i} className="relative" title={`${c.name} — score ${c.score.toFixed(1)}`}>
                  <span className="absolute -top-1 -right-1 z-10 rounded bg-red-900 px-1 text-xs text-red-400">
                    {c.score.toFixed(0)}
                  </span>
                  <CardImage id={c.card_id} name={c.name} />
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function HandScoreDisplay({ hss }: { hss: HandScoreStats | null }) {
  if (!hss) return null;
  const diff = hss.avg_win - hss.avg_loss;
  const cls = diff > 2 ? "text-green-400" : diff < -2 ? "text-red-400" : "text-slate-400";
  return (
    <div className="my-2 rounded border border-slate-700 bg-slate-900/50 p-2 text-sm">
      <Tooltip label="Score main moyen" text={STATS_TIPS.score_main} /> :{" "}
      <span className="text-green-400">V {hss.avg_win.toFixed(1)}</span>
      <span className="text-slate-500"> vs </span>
      <span className="text-red-400">D {hss.avg_loss.toFixed(1)}</span>
      <span className={`ml-2 ${cls}`}>(Δ {diff > 0 ? "+" : ""}{diff.toFixed(1)})</span>
      <span className="ml-2 text-xs text-slate-600">n={hss.n_win}V / {hss.n_loss}D</span>
    </div>
  );
}
