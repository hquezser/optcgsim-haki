"use client";

import type { PlayerState, CounterAnalysis, TriggerRisk, MatchupStats, HandScore } from "@/lib/types";
import { CardChips, GroupedCards } from "./Card";
import { LifeDisplay } from "./LifeDisplay";
import { Tooltip } from "./Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";

interface PlayerPanelProps {
  player: PlayerState | null;
  variant: "me" | "opp";
  counterAnalysis?: CounterAnalysis;
  handScore?: HandScore;
  matchupStats?: MatchupStats;
  triggerRisk?: TriggerRisk;
  coachMode?: boolean;
}

export function PlayerPanel({
  player,
  variant,
  counterAnalysis,
  handScore,
  matchupStats,
  triggerRisk,
  coachMode = false,
}: PlayerPanelProps) {
  if (!player) return null;
  const isMe = variant === "me";
  const isOpp = variant === "opp";
  const hcApprox = player.hand_count_approx;
  const hc =
    player.hand_count == null
      ? "?"
      : (hcApprox ? "≈" : "") + player.hand_count;

  const hand =
    player.hand === null ? (
      <div className="text-slate-500 text-sm py-2">
        {player.hand_count == null
          ? "cachée (fair-play)"
          : `${hcApprox ? "≈" : ""}${player.hand_count} cartes (cachées — fair-play)`}
      </div>
    ) : (
      <div>
        {player.hand_approx && (
          <div className="mb-1 text-[11px] text-amber-500/80" title="Reconstruite depuis le log : exacte sur pioches/plays, mais dérive sur les effets manipulant la main (prise de life, mise sur le deck, tutor). Les '?' sont des cartes dont l'identité n'est pas révélée par le log.">
            ≈ main reconstruite (best-effort, peut dériver sur effets)
          </div>
        )}
        <CardChips cards={player.hand} />
      </div>
    );

  // Counter analysis (opp only) — en mode Coach, seulement si alerte (counters restants ≥2)
  let counterRow = null;
  if (isOpp && counterAnalysis) {
    const p2 = counterAnalysis.plus2k_in_trash;
    const exp = counterAnalysis.plus2k_expected;
    const remaining = (exp ?? 0) - (p2 ?? 0);
    const isAlert = remaining >= 2;

    // En mode Coach : on n'affiche que les alertes. En mode Full : toujours.
    if (!coachMode || isAlert) {
      const ratio = exp != null ? ` / ~${exp} estimés` : "";
      const cls =
        exp != null && p2 >= exp * 0.6
          ? "bg-green-900/50 text-green-400 border-green-700"
          : p2 >= 4
          ? "bg-amber-900/30 text-amber-400 border-amber-700"
          : "bg-red-900/30 text-red-400 border-red-700";
      let defBadge = null;
      if (counterAnalysis.avg_counter != null && player.hand_count != null) {
        const est = Math.round((counterAnalysis.avg_counter * player.hand_count) / 500) * 500;
        defBadge = (
          <span className="ml-2 rounded bg-slate-700/50 px-2 py-0.5 text-xs text-slate-300">
            Défense est. ~{est.toLocaleString()}
          </span>
        );
      }
      counterRow = (
        <div className="my-1.5">
          <span className={`rounded border px-2 py-0.5 text-xs ${cls}`}>
            <Tooltip label={`+2000 défaussés : ${p2}${ratio}`} text={STATS_TIPS.counter_analysis} />
          </span>
          {defBadge}
        </div>
      );
    }
  }

  // Hand score (me only) — en mode Coach, seulement si Mulligan
  let handScoreRow = null;
  if (isMe && handScore) {
    const isAlert = handScore.verdict === "Mulligan";
    if (!coachMode || isAlert) {
      const cls =
        handScore.verdict === "Garder"
          ? "bg-green-900/50 text-green-400 border-green-700"
          : handScore.verdict === "Mulligan"
          ? "bg-red-900/50 text-red-400 border-red-700"
          : "bg-slate-700/50 text-slate-400 border-slate-600";
      const sign = handScore.score > 0 ? "+" : "";
      handScoreRow = (
        <div className="my-1.5">
          <span className={`rounded border px-2 py-0.5 text-xs ${cls}`}>
            <Tooltip label={`Main : ${sign}${handScore.score} — ${handScore.verdict}`} text={STATS_TIPS.hand_score} />
          </span>
        </div>
      );
    }
  }

  // Matchup WR (opp only) — en mode Coach, seulement si WR extrême (≤35% ou ≥65%)
  let muBadge = null;
  if (isOpp && matchupStats && matchupStats.n > 0) {
    const wr = matchupStats.wr;
    const isAlert = wr != null && (wr <= 35 || wr >= 65) && matchupStats.n >= 3;
    if (!coachMode || isAlert) {
      const cls = isAlert
        ? wr! <= 35
          ? "bg-red-900/40 text-red-400"
          : "bg-green-900/40 text-green-400"
        : "bg-slate-700/50 text-slate-300";
      muBadge = (
        <span className={`ml-2 rounded px-2 py-0.5 text-xs ${cls}`}>
          <Tooltip label={`${wr != null ? `${wr}%` : " ?"} WR • ${matchupStats.n}p`} text={STATS_TIPS.matchup_stats} />
        </span>
      );
    }
  }

  // Trigger risk (opp only) — en mode Coach, seulement si ≥30% ou opp à ≤2 vies
  let triggerBadge = null;
  if (isOpp && triggerRisk && triggerRisk.pct != null) {
    const lowLife = player.life != null && player.life <= 2;
    const isAlert = triggerRisk.pct >= 30 || (lowLife && triggerRisk.pct >= 15);
    if (!coachMode || isAlert) {
      const cls =
        triggerRisk.pct >= 30
          ? "bg-orange-900/40 text-orange-400"
          : triggerRisk.pct >= 15
          ? "bg-amber-900/30 text-amber-400"
          : "bg-slate-700/40 text-slate-400";
      const tipText = `⚡${triggerRisk.pct}% — ${triggerRisk.remaining} triggers restants / ${triggerRisk.unknown} cartes inconnues. ${STATS_TIPS.trigger_risk}`;
      triggerBadge = (
        <span className={`ml-1 rounded px-1.5 py-0.5 text-xs ${cls}`}>
          <Tooltip label={`⚡${triggerRisk.pct}%`} text={tipText} />
        </span>
      );
    }
  }

  // Trash (opp = collapsible, me = visible)
  const trashBlock = isOpp ? (
    <details className="mt-1">
      <summary className="cursor-pointer text-xs uppercase tracking-wide text-slate-500">
        ▸ Trash ({(player.trash || []).length})
      </summary>
      <div className="mt-1">
        <GroupedCards cards={player.trash} />
      </div>
    </details>
  ) : (
    <div>
      <div className="mt-2 text-xs uppercase tracking-wide text-slate-500">Trash</div>
      <CardChips cards={player.trash} />
    </div>
  );

  return (
    <section className={`rounded-lg border p-3 ${isMe ? "border-slate-700 bg-slate-900/50" : "border-slate-700 bg-slate-900/30"}`}>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <span>{isMe ? "MOI" : "ADVERSAIRE"} — {player.leader_name || player.leader || "?"}</span>
        {muBadge}
      </h2>
      <div className="flex gap-4 text-sm">
        <span>Life <LifeDisplay life={player.life} />{triggerBadge}</span>
        <span>Deck <b>{player.deck_remaining ?? "?"}</b></span>
        <span>Main <b>{hc}</b></span>
      </div>
      {counterRow}
      {handScoreRow}
      <div className="mt-2 text-xs uppercase tracking-wide text-slate-500">Main</div>
      {hand}
      <div className="mt-2 text-xs uppercase tracking-wide text-slate-500">
        {isOpp ? "Joué (board)" : "Board"}
      </div>
      <CardChips cards={player.board} />
      {trashBlock}
    </section>
  );
}
