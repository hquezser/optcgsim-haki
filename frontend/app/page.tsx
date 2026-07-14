"use client";

import { useEffect, useState, useRef } from "react";
import { fetchState, toggleReveal } from "@/lib/api";
import type { LiveState } from "@/lib/types";
import { PlayerPanel } from "@/components/PlayerPanel";
import { LethalPanel } from "@/components/LethalPanel";
import { MenacesPanel } from "@/components/MenacesPanel";
import { ArchetypePanel } from "@/components/ArchetypePanel";
import { DrawOddsPanel } from "@/components/DrawOddsPanel";
import { CoachAlerts } from "@/components/CoachAlerts";
import { Collapsible } from "@/components/Collapsible";
import { TooltipIcon } from "@/components/Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";
import { MatchBar, ResultBanner, RecentBar } from "@/components/MatchBar";

export default function LiveDashboard() {
  const [data, setData] = useState<LiveState | null>(null);
  const [connected, setConnected] = useState(false);
  const [coachMode, setCoachMode] = useState(true);
  const frozenResult = useRef<string | null>(null);

  useEffect(() => {
    const tick = async () => {
      const d = await fetchState();
      setConnected(d != null);
      if (d) setData(d);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const status = data?.result
    ? `terminé — ${["win", "me_wins", "opp_concede", "opponent_disconnect"].includes(data.result) ? "victoire" : "défaite"}`
    : data?.active
    ? "partie en cours"
    : "en attente…";

  const statusCls = data?.active && !data?.result ? "bg-green-900/50 text-green-400" : "bg-slate-700 text-slate-400";

  const showResult = data?.result && frozenResult.current !== data.result;
  if (data?.result) frozenResult.current = data.result;
  if (!data?.result) frozenResult.current = null;

  const empty = !data?.me && !data?.opp;

  // En mode Coach : les panneaux détaillés sont fermés par défaut.
  // En mode Full : tout est ouvert.
  const defaultOpen = !coachMode;

  // Lethal est toujours visible (déjà conditionnel dans LethalPanel).
  const hasLethal = data?.lethal && (data.lethal.opp_can_lethal || data.lethal.me_can_lethal);

  // Feature flags : ne rendre les panneaux approximatifs que si le flag correspondant est ON.
  // En mode exact, le backend force ces flags ON → les panneaux réapparaissent automatiquement.
  const showLethal = data?.features?.live_lethal !== false;
  const showMenaces = data?.features?.live_menaces !== false;
  const showArchetype = data?.features?.live_archetype !== false;
  const showDrawOdds = data?.features?.live_draw_odds !== false && !!data?.draw_odds;

  return (
    <div className="mx-auto max-w-7xl px-4 py-4">
      {/* Header */}
      <header className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-bold">OPTCGSim Haki — Live</h1>
        <span className={`rounded-full px-3 py-0.5 text-sm ${statusCls}`}>{status}</span>
        {data?.exact_state && (
          <span
            className="rounded-full bg-green-900/50 px-3 py-0.5 text-sm text-green-400"
            title="État servi par le mod BepInEx (exact), pas par le parsing de log (inféré)"
          >
            ⚡ état exact
          </span>
        )}
        {data?.room_code && (
          <span className="rounded-full bg-slate-700 px-3 py-0.5 text-sm text-slate-400">
            salle {data.room_code}
          </span>
        )}
        {/* Toggle reveal-all : expose la main + l'ordre du deck adverses. ⚠️ Triche en classé. */}
        <button
          onClick={async () => {
            if (!data?.reveal_all &&
                !confirm("⚠️ Reveal-all expose la MAIN et l'ordre du DECK adverses (reconstruits depuis le log).\n\nÀ usage hors-ligne / revue uniquement. L'utiliser en partie classée en ligne est de la triche.\n\nActiver ?")) {
              return;
            }
            await toggleReveal();
            const d = await fetchState();
            if (d) setData(d);
          }}
          className={`rounded-full px-3 py-0.5 text-sm transition-colors ${
            data?.reveal_all
              ? "bg-amber-900/60 text-amber-300 border border-amber-600"
              : "bg-slate-800 text-slate-400 border border-slate-700"
          }`}
          title="Révéler la main + le deck adverses (hors-ligne / revue uniquement)"
        >
          {data?.reveal_all ? "👁️ reveal-all ON" : "🙈 fair-play"}
        </button>
        <span className="ml-auto flex items-center gap-4 text-sm">
          {/* Toggle Coach / Full */}
          <button
            onClick={() => setCoachMode(!coachMode)}
            className={`rounded-full px-3 py-0.5 text-sm transition-colors ${
              coachMode
                ? "bg-blue-900/50 text-blue-400 border border-blue-700"
                : "bg-slate-700 text-slate-400 border border-slate-600"
            }`}
            title={coachMode ? "Mode Coach : alertes synthétiques uniquement" : "Mode Full : tous les détails"}
          >
            {coachMode ? "🧭 Coach" : "📊 Full"}
          </button>
          <a href="/overlay" className="text-blue-400 hover:underline">Overlay</a>
        </span>
      </header>

      {!connected && (
        <div className="rounded border border-amber-700 bg-amber-950/30 p-3 text-amber-400 text-sm">
          Serveur API injoignable. Lance le backend : <code className="bg-slate-800 px-1 rounded">optcgsim-haki dashboard</code>
        </div>
      )}

      {connected && empty && (
        <div className="rounded border border-slate-700 bg-slate-900 p-6 text-center text-slate-500">
          En attente d'une partie… Lance une partie dans OPTCGSim.
        </div>
      )}

      {connected && !empty && (
        <>
          <div className="mb-3">
            <MatchBar data={data!} />
          </div>

          {/* Coach Alerts — toujours visible en mode Coach, supprimé en mode Full */}
          {coachMode && (
            <div className="mb-3">
              <CoachAlerts data={data!} />
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {showResult && <ResultBanner result={data!.result!} winReason={data!.win_reason} />}

            {/* Lethal — visible s'il y a un danger, collapsible sinon (gated par flag) */}
            {showLethal && (hasLethal ? (
              <LethalPanel lethal={data!.lethal} />
            ) : (
              <Collapsible title={<span>⚔️ Lethal Risk<TooltipIcon text={STATS_TIPS.lethal} /></span>} defaultOpen={defaultOpen}>
                <LethalPanel lethal={data!.lethal} />
              </Collapsible>
            ))}

            {/* Player panels — toujours visibles (info essentielle) */}
            <PlayerPanel
              player={data!.me ?? null}
              variant="me"
              handScore={data!.hand_score}
              coachMode={coachMode}
            />
            <PlayerPanel
              player={data!.opp ?? null}
              variant="opp"
              counterAnalysis={data!.counter_analysis}
              matchupStats={data!.matchup_stats}
              triggerRisk={data!.trigger_risk}
              coachMode={coachMode}
            />

            {/* Menaces — collapsible en mode Coach (gated par flag) */}
            {showMenaces && (
              <Collapsible
                title={<span>🎯 Menaces probables (T+1)<TooltipIcon text={STATS_TIPS.next_plays} /></span>}
                defaultOpen={defaultOpen}
                badge={
                  data?.next_plays && data.next_plays.length > 0 ? (
                    <span className="rounded bg-orange-900/40 px-1.5 py-0.5 text-xs text-orange-400">
                      {data.next_plays.length}
                    </span>
                  ) : undefined
                }
              >
                <MenacesPanel
                  list={data!.next_plays}
                  donEst={data!.opp_don_est}
                  phase={data!.next_plays_phase}
                  turn={data!.next_plays_turn}
                />
              </Collapsible>
            )}

            {/* Archétype — collapsible en mode Coach (gated par flag) */}
            {showArchetype && (
              <Collapsible
                title={<span>Archétype adverse<TooltipIcon text={STATS_TIPS.archetype} /></span>}
                defaultOpen={defaultOpen}
                badge={
                  data?.archetype ? (
                    <span className="text-xs text-slate-400">{data.archetype.leader_name}</span>
                  ) : undefined
                }
              >
                <ArchetypePanel archetype={data!.archetype} donEst={data!.opp_don_est} />
              </Collapsible>
            )}

            {/* Odds de pioche (gated live_draw_odds) — ma prochaine pioche */}
            {showDrawOdds && (
              <Collapsible
                title={<span>Odds de pioche<TooltipIcon text="Probabilité hypergéométrique de piocher chaque carte dès ta prochaine pioche (deck + vies non vus)." /></span>}
                defaultOpen={defaultOpen}
                badge={
                  <span className="text-xs text-slate-400">
                    {data!.draw_odds!.mode === "exact" ? "⚡ exact" : "approx"}
                  </span>
                }
              >
                <DrawOddsPanel odds={data!.draw_odds!} />
              </Collapsible>
            )}
          </div>
        </>
      )}

      {/* Recent matches bar */}
      {data?.recent_matches && data.recent_matches.length > 0 && (
        <div className="mt-6 max-w-5xl mx-auto">
          <RecentBar matches={data.recent_matches} />
        </div>
      )}
    </div>
  );
}
