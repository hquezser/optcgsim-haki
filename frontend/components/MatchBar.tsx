"use client";

import type { LiveState } from "@/lib/types";

export function MatchBar({ data }: { data: LiveState }) {
  if (!data || (!data.me && !data.opp)) return null;
  const items: React.ReactNode[] = [];
  if (data.me_don_est != null)
    items.push(
      <span key="me-don" className="flex items-center gap-1 text-sm">
        Mon DON <span className="font-bold text-blue-400">~{data.me_don_est} ⬡</span>
      </span>
    );
  if (data.opp_don_est != null)
    items.push(
      <span key="opp-don" className="flex items-center gap-1 text-sm">
        DON adverse <span className="font-bold text-red-400">~{data.opp_don_est} ⬡</span>
      </span>
    );
  if (data.me && data.me.life != null)
    items.push(
      <span key="me-life" className="flex items-center gap-1 text-sm">
        Ma vie <b className={data.me.life <= 2 ? "text-red-400 animate-pulse" : ""}>{data.me.life}</b>
      </span>
    );
  if (items.length === 0) return null;
  return <div className="flex gap-4 rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2">{items}</div>;
}

export function ResultBanner({
  result,
  winReason,
}: {
  result: string;
  winReason?: string | null;
}) {
  const isWin = ["win", "me_wins", "opp_concede", "opponent_disconnect"].includes(result);
  const reasonText: Record<string, string> = {
    concede: isWin ? "— adversaire abandonne" : "— abandon",
    disconnect: "— adversaire déconnecté",
    damage: "— par dégâts",
    inferred: "— (déduit)",
  };
  const reason = winReason ? reasonText[winReason] || "" : "";
  return (
    <div
      className={`rounded-lg border p-3 text-center ${
        isWin
          ? "border-green-700 bg-gradient-to-r from-green-950 to-slate-950 text-green-400"
          : "border-red-800 bg-gradient-to-r from-red-950 to-slate-950 text-red-400"
      }`}
    >
      <span className="text-lg font-bold">{isWin ? "🏆 Victoire" : "💀 Défaite"} {reason}</span>
      <div className="text-xs text-slate-500">Partie terminée — en attente de la suivante…</div>
    </div>
  );
}

export function RecentBar({
  matches,
}: {
  matches?: { result: string; opp_leader: string; opp_name: string }[];
}) {
  if (!matches || matches.length === 0) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-slate-500">Récents :</span>
      {matches.map((m, i) => (
        <span key={i} className="flex items-center gap-1 text-sm">
          <span
            className={`rounded px-1 text-xs font-bold ${
              m.result === "win" ? "bg-green-900 text-green-400" : "bg-red-900 text-red-400"
            }`}
          >
            {m.result === "win" ? "V" : "D"}
          </span>
          {m.opp_name || m.opp_leader}
        </span>
      ))}
    </div>
  );
}
