"use client";

import type { StatsRow } from "@/lib/stats-types";
import Link from "next/link";

export function WinrateBar({ row, href }: { row: StatsRow; href?: string }) {
  const pct = row.winrate;
  const cls = pct >= 50 ? "bg-green-600" : "bg-red-600";
  const content = (
    <div className="flex items-center gap-2 py-1 border-b border-slate-800">
      <span className="w-48 truncate text-sm text-slate-300">{row.label}</span>
      <span className="flex-1 rounded bg-slate-900 h-3.5 overflow-hidden">
        <span className={`block h-full ${cls}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="w-24 text-right text-sm tabular-nums text-slate-400">
        {pct.toFixed(0)}% <span className="text-slate-600">({row.wins}-{row.losses})</span>
      </span>
    </div>
  );
  if (href) return <Link href={href}>{content}</Link>;
  return content;
}

export function WinrateBars({ rows, linkFn }: { rows: StatsRow[]; linkFn?: (r: StatsRow) => string }) {
  if (!rows || rows.length === 0) return <p className="text-slate-500 text-sm">—</p>;
  return (
    <div>
      {rows.map((r, i) => (
        <WinrateBar key={i} row={r} href={linkFn?.(r)} />
      ))}
    </div>
  );
}
