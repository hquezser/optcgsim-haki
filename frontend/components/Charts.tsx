"use client";

import type { CurveData, AttackDist, CounterStats, DonWasteData } from "@/lib/stats-types";

export function CurveChart({
  data,
  ylabel,
}: {
  data: CurveData | null;
  ylabel: string;
}) {
  if (!data) return <p className="text-slate-500 text-sm">Échantillon insuffisant.</p>;
  const allPts = [...data.win, ...data.loss];
  if (allPts.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  const maxTurn = Math.max(...allPts.map((p) => p[0]));
  const maxVal = Math.max(...allPts.map((p) => p[1]));
  const minVal = Math.min(...allPts.map((p) => p[1]), 0);
  const W = 400, H = 120, PAD = 30;
  const xScale = (t: number) => PAD + (t / Math.max(1, maxTurn)) * (W - PAD - 10);
  const yScale = (v: number) => H - PAD - ((v - minVal) / Math.max(1, maxVal - minVal)) * (H - PAD - 10);

  const path = (pts: [number, number][]) =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"} ${xScale(p[0])} ${yScale(p[1])}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-md">
      {/* Axes */}
      <line x1={PAD} y1={H - PAD} x2={W - 10} y2={H - PAD} stroke="#3a4452" />
      <line x1={PAD} y1={10} x2={PAD} y2={H - PAD} stroke="#3a4452" />
      {/* Y label */}
      <text x={5} y={H / 2} fill="#8b95a5" fontSize={10} transform={`rotate(-90 10 ${H / 2})`}>{ylabel}</text>
      {/* X label */}
      <text x={W / 2} y={H - 2} fill="#8b95a5" fontSize={10} textAnchor="middle">Tour</text>
      {/* Win curve (green) */}
      {data.win.length > 0 && (
        <>
          <path d={path(data.win)} fill="none" stroke="#3fb950" strokeWidth={2} />
          {data.win.map((p, i) => (
            <circle key={i} cx={xScale(p[0])} cy={yScale(p[1])} r={2.5} fill="#3fb950" />
          ))}
        </>
      )}
      {/* Loss curve (red) */}
      {data.loss.length > 0 && (
        <>
          <path d={path(data.loss)} fill="none" stroke="#e0566a" strokeWidth={2} strokeDasharray="4 2" />
          {data.loss.map((p, i) => (
            <circle key={i} cx={xScale(p[0])} cy={yScale(p[1])} r={2.5} fill="#e0566a" />
          ))}
        </>
      )}
      {/* Legend */}
      <rect x={W - 80} y={12} width={8} height={8} fill="#3fb950" />
      <text x={W - 68} y={20} fill="#8b95a5" fontSize={10}>Victoires ({data.n_win})</text>
      <rect x={W - 80} y={26} width={8} height={8} fill="#e0566a" />
      <text x={W - 68} y={34} fill="#8b95a5" fontSize={10}>Défaites ({data.n_loss})</text>
    </svg>
  );
}

export function AttackDistChart({ data }: { data: AttackDist | null }) {
  if (!data) return <p className="text-slate-500 text-sm">Échantillon insuffisant.</p>;
  return (
    <div className="space-y-2">
      {(["win", "loss"] as const).map((res) => {
        const d = data[res];
        const cls = res === "win" ? "text-green-400" : "text-red-400";
        const label = res === "win" ? "Victoires" : "Défaites";
        return (
          <div key={res} className="flex items-center gap-2">
            <span className="w-20 text-sm text-slate-400">{label}</span>
            <span className="flex-1 rounded bg-slate-900 h-4 overflow-hidden">
              <span className={`block h-full ${res === "win" ? "bg-green-600" : "bg-red-600"}`} style={{ width: `${d.life_pct}%` }} />
            </span>
            <span className={`text-sm tabular-nums ${cls}`}>
              {d.life_pct.toFixed(0)}% leader
            </span>
            <span className="text-xs text-slate-600">n={d.n}</span>
          </div>
        );
      })}
    </div>
  );
}

export function CounterStatsDisplay({ data }: { data: CounterStats | null }) {
  if (!data) return <p className="text-slate-500 text-sm">Échantillon insuffisant.</p>;
  return (
    <div className="space-y-2">
      {(["win", "loss"] as const).map((res) => {
        const d = data[res];
        const cls = res === "win" ? "text-green-400" : "text-red-400";
        const label = res === "win" ? "Victoires" : "Défaites";
        return (
          <div key={res} className="flex items-center gap-4 text-sm">
            <span className="w-20 text-slate-400">{label}</span>
            <span className={cls}>{d.avg_value.toLocaleString()} power</span>
            <span className="text-slate-500">{d.avg_count.toFixed(1)} counters/partie</span>
          </div>
        );
      })}
    </div>
  );
}

export function DonWasteDisplay({ data }: { data: DonWasteData | null }) {
  if (!data) return <p className="text-slate-500 text-sm">Échantillon insuffisant.</p>;
  return (
    <div className="space-y-3">
      <CurveChart data={data.curve} ylabel="DON gaspillé" />
      <div className="space-y-1">
        {(["win", "loss"] as const).map((res) => {
          const d = data.summary[res];
          const cls = res === "win" ? "text-green-400" : "text-red-400";
          const label = res === "win" ? "Victoires" : "Défaites";
          return (
            <div key={res} className="flex items-center gap-4 text-sm">
              <span className="w-20 text-slate-400">{label}</span>
              <span className={cls}>{d.avg_total.toFixed(1)} DON gaspillé/partie</span>
              <span className="text-slate-500">{d.avg_per_turn.toFixed(2)}/tour</span>
              <span className="text-xs text-slate-600">n={d.n}</span>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-slate-600">
        DON disponible non utilisé en fin de tour (déploiements + attachements). Un waste
        faible = courbe de mana bien optimisée.
      </p>
    </div>
  );
}
