"use client";

import { useState, useMemo } from "react";
import type { MatchTimeline, TurnSnapshot, Highlight, ValueTurnEntry } from "@/lib/match-types";
import { CardImage } from "./Card";

/**
 * MatchTimeline — frise chronologique interactive post-match.
 *
 * Superpose :
 * - Courbe de vie (me vs opp) sur tous les tours
 * - Compte de main (me vs opp) en option
 * - Highlights cliquables (moments clés détectés)
 * - Détail des events au tour sélectionné
 */
export function MatchTimelineView({ data }: { data: MatchTimeline }) {
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);
  const [showHand, setShowHand] = useState(false);

  const { match, snapshots, events, highlights, value_timeline } = data;

  // Index snapshots par (turn, side) → dernière valeur du tour.
  const lifeByTurn = useMemo(() => indexByTurn(snapshots, "life"), [snapshots]);
  const handByTurn = useMemo(() => indexByTurn(snapshots, "hand_count"), [snapshots]);
  const deckByTurn = useMemo(() => indexByTurn(snapshots, "deck_remaining"), [snapshots]);

  const allTurns = useMemo(() => {
    const turns = new Set<number>();
    for (const s of snapshots) turns.add(s.turn);
    for (const e of events) turns.add(e.turn);
    return Array.from(turns).sort((a, b) => a - b);
  }, [snapshots, events]);

  if (allTurns.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 p-4 text-center text-slate-500">
        Aucune donnée de timeline pour cette partie (snapshots manquants).
      </div>
    );
  }

  const maxLife = Math.max(...snapshots.map(s => s.life ?? 0).filter(l => l > 0), 5);
  const maxHand = Math.max(...snapshots.map(s => s.hand_count ?? 0).filter(h => h > 0), 10);

  // Events du tour sélectionné.
  const turnEvents = selectedTurn != null
    ? events.filter(e => e.turn === selectedTurn)
    : [];
  const turnHighlights = selectedTurn != null
    ? highlights.filter(h => h.turn === selectedTurn)
    : [];
  const turnValue = value_timeline?.find(v => v.turn === selectedTurn);

  return (
    <div className="space-y-4">
      {/* Header : infos match */}
      <div className="flex items-center gap-4 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
        <div className="flex items-center gap-2">
          {match.my_leader && <CardImage id={match.my_leader} name={match.my_leader_name} />}
          <div>
            <div className="text-sm font-semibold">{match.my_leader_name || "?"}</div>
            <div className="text-xs text-slate-500">toi</div>
          </div>
        </div>
        <span className="text-lg text-slate-600">vs</span>
        <div className="flex items-center gap-2">
          {match.opp_leader && <CardImage id={match.opp_leader} name={match.opp_leader_name} />}
          <div>
            <div className="text-sm font-semibold">{match.opp_leader_name || "?"}</div>
            <div className="text-xs text-slate-500">adversaire</div>
          </div>
        </div>
        <span className={`ml-auto rounded-full px-3 py-0.5 text-sm font-semibold ${
          match.result === "win" ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"
        }`}>
          {match.result === "win" ? "Victoire" : "Défaite"}
          {match.win_reason && match.win_reason !== "unknown" && ` · ${match.win_reason}`}
        </span>
      </div>

      {/* Toggle vie / main */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setShowHand(false)}
          className={`rounded px-3 py-1 text-sm ${!showHand ? "bg-blue-900/50 text-blue-400" : "bg-slate-800 text-slate-500"}`}
        >
          ❤️ Vie
        </button>
        <button
          onClick={() => setShowHand(true)}
          className={`rounded px-3 py-1 text-sm ${showHand ? "bg-blue-900/50 text-blue-400" : "bg-slate-800 text-slate-500"}`}
        >
          🃏 Main
        </button>
      </div>

      {/* Graphique timeline */}
      <TimelineChart
        turns={allTurns}
        meData={showHand ? handByTurn.me : lifeByTurn.me}
        oppData={showHand ? handByTurn.opp : lifeByTurn.opp}
        maxValue={showHand ? maxHand : maxLife}
        color={showHand ? "hand" : "life"}
        highlights={highlights}
        selectedTurn={selectedTurn}
        onSelectTurn={setSelectedTurn}
      />

      {/* Graphique Value Score par tour */}
      {value_timeline && value_timeline.length > 0 && (
        <ValueBarChart
          data={value_timeline}
          selectedTurn={selectedTurn}
          onSelectTurn={setSelectedTurn}
        />
      )}

      {/* Détail du tour sélectionné */}
      {selectedTurn != null && (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <h3 className="mb-2 text-sm font-semibold">Tour {selectedTurn}</h3>

          {/* Stats du tour */}
          <div className="mb-3 flex gap-6 text-sm">
            <div>
              <span className="text-slate-500">Toi : </span>
              <span className="font-semibold">❤️ {lifeByTurn.me[selectedTurn] ?? "?"}</span>
              <span className="ml-2 text-slate-500">🃏 {handByTurn.me[selectedTurn] ?? "?"}</span>
              <span className="ml-2 text-slate-500">📦 {deckByTurn.me[selectedTurn] ?? "?"}</span>
            </div>
            <div>
              <span className="text-slate-500">Adv : </span>
              <span className="font-semibold">❤️ {lifeByTurn.opp[selectedTurn] ?? "?"}</span>
              <span className="ml-2 text-slate-500">🃏 {handByTurn.opp[selectedTurn] ?? "?"}</span>
              <span className="ml-2 text-slate-500">📦 {deckByTurn.opp[selectedTurn] ?? "?"}</span>
            </div>
          </div>

          {/* Highlights du tour */}
          {turnHighlights.length > 0 && (
            <div className="mb-3 space-y-1">
              {turnHighlights.map((h, i) => (
                <div key={i} className={`flex items-center gap-2 rounded px-2 py-1 text-sm ${
                  h.side === "me" ? "bg-blue-950/30 text-blue-300" : "bg-red-950/30 text-red-300"
                }`}>
                  <span>{h.icon}</span>
                  <span>{h.label}</span>
                </div>
              ))}
            </div>
          )}

          {/* Value Score du tour */}
          {turnValue && (
            <div className={`mb-3 rounded p-2 text-sm ${
              turnValue.value < 0
                ? "bg-red-950/30 border border-red-900/50"
                : turnValue.value > 5
                ? "bg-green-950/30 border border-green-900/50"
                : "bg-slate-800/30 border border-slate-700/50"
            }`}>
              <span className="text-slate-400">Value du tour : </span>
              <span className={`font-bold ${turnValue.value < 0 ? "text-red-400" : "text-green-400"}`}>
                {turnValue.value > 0 ? "+" : ""}{turnValue.value}
              </span>
              <span className="ml-2 text-slate-500">(cumul : {turnValue.cumulative > 0 ? "+" : ""}{turnValue.cumulative})</span>
              {turnValue.value < 0 && (
                <span className="ml-2 text-xs text-red-500">⚠ Misplay probable</span>
              )}
              {turnValue.value > 8 && (
                <span className="ml-2 text-xs text-green-500">⭐ Tour pivot</span>
              )}
              {turnValue.deploys.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-2">
                  {turnValue.deploys.map((d, i) => (
                    <span key={i} className="flex items-center gap-1 text-xs">
                      <CardImage id={d.card_id} name={d.name} className="w-6 h-8" />
                      <span className="text-slate-400">{d.name}</span>
                      <span className={d.value >= 0 ? "text-green-400" : "text-red-400"}>
                        {d.value > 0 ? "+" : ""}{d.value}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Events du tour */}
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">Événements</div>
            {turnEvents.length === 0 ? (
              <div className="text-sm text-slate-600">—</div>
            ) : (
              turnEvents.map((e, i) => (
                <div key={i} className={`flex items-center gap-2 text-sm ${
                  e.side === "me" ? "text-blue-300" : "text-red-300"
                }`}>
                  <span className="w-3 text-center">{e.side === "me" ? "🔵" : "🔴"}</span>
                  <span className="w-20 text-xs text-slate-500">{eventLabel(e.type)}</span>
                  {e.card_id && <CardImage id={e.card_id} name={e.card_name} />}
                  <span className="flex-1 truncate">{e.card_name || "—"}</span>
                  {e.target_name && (
                    <span className="text-xs text-slate-500">→ {e.target_name}</span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Légende des highlights */}
      {highlights.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-900/30 p-2">
          <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Moments clés</div>
          <div className="flex flex-wrap gap-2">
            {highlights.map((h, i) => (
              <button
                key={i}
                onClick={() => setSelectedTurn(h.turn)}
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
                  selectedTurn === h.turn
                    ? "bg-slate-700 text-slate-200"
                    : "bg-slate-800/50 text-slate-400 hover:bg-slate-800"
                }`}
              >
                <span>{h.icon}</span>
                <span>T{h.turn}</span>
                <span className="text-slate-600">{h.side === "me" ? "toi" : "adv"}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --- Sub-components ---

function ValueBarChart({
  data,
  selectedTurn,
  onSelectTurn,
}: {
  data: ValueTurnEntry[];
  selectedTurn: number | null;
  onSelectTurn: (t: number) => void;
}) {
  const maxAbs = Math.max(...data.map(d => Math.abs(d.value)), 1);
  const H = 120;
  const barH = 50;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
      <h3 className="mb-2 text-sm font-semibold text-slate-300">
        📊 Value Score par tour
        <span className="ml-2 text-xs font-normal text-slate-500">
          (rouge = misplay · vert = tour pivot)
        </span>
      </h3>
      <div className="flex items-end gap-1" style={{ height: H }}>
        {data.map((d) => {
          const pct = Math.min(100, (Math.abs(d.value) / maxAbs) * 100);
          const isPositive = d.value >= 0;
          const barCls = d.value < 0
            ? "bg-red-600"
            : d.value > 8
            ? "bg-green-500"
            : "bg-green-700";
          const barHeight = (pct / 100) * barH;
          return (
            <button
              key={d.turn}
              onClick={() => onSelectTurn(d.turn)}
              className="flex flex-col items-center gap-0.5"
              title={`T${d.turn} : ${d.value > 0 ? "+" : ""}${d.value} (cumul ${d.cumulative > 0 ? "+" : ""}${d.cumulative})`}
            >
              <span className="text-[10px] tabular-nums text-slate-500">
                {d.value > 0 ? "+" : ""}{d.value}
              </span>
              <div className="flex flex-col justify-center" style={{ height: barH * 2 }}>
                {isPositive ? (
                  <div className={`rounded-t ${barCls} w-6`} style={{ height: barHeight, alignSelf: "flex-end" }} />
                ) : (
                  <div className={`rounded-b ${barCls} w-6`} style={{ height: barHeight, alignSelf: "flex-start" }} />
                )}
              </div>
              <span className={`text-[10px] tabular-nums ${selectedTurn === d.turn ? "text-slate-200 font-bold" : "text-slate-500"}`}>
                T{d.turn}
              </span>
            </button>
          );
        })}
      </div>
      {/* Ligne de zero */}
      <div className="mt-1 text-xs text-slate-600">
        Cumul : {data.length > 0 ? (data[data.length - 1].cumulative > 0 ? "+" : "") + data[data.length - 1].cumulative : "—"}
      </div>
    </div>
  );
}

function TimelineChart({
  turns,
  meData,
  oppData,
  maxValue,
  color,
  highlights,
  selectedTurn,
  onSelectTurn,
}: {
  turns: number[];
  meData: Record<number, number>;
  oppData: Record<number, number>;
  maxValue: number;
  color: "life" | "hand";
  highlights: Highlight[];
  selectedTurn: number | null;
  onSelectTurn: (t: number) => void;
}) {
  const W = Math.max(400, turns.length * 40);
  const H = 200;
  const padL = 30;
  const padB = 25;
  const padT = 10;
  const padR = 10;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const xScale = (turn: number) => {
    if (turns.length <= 1) return padL + chartW / 2;
    return padL + (chartW * (turn - turns[0])) / (turns[turns.length - 1] - turns[0]);
  };
  const yScale = (val: number) => padT + chartH - (chartH * val) / maxValue;

  const mePoints = turns.filter(t => meData[t] != null).map(t => ({ x: xScale(t), y: yScale(meData[t]), turn: t }));
  const oppPoints = turns.filter(t => oppData[t] != null).map(t => ({ x: xScale(t), y: yScale(oppData[t]), turn: t }));

  const mePath = toPath(mePoints);
  const oppPath = toPath(oppPoints);

  const meColor = color === "life" ? "#3b82f6" : "#06b6d4";
  const oppColor = color === "life" ? "#ef4444" : "#f97316";

  // Highlights par tour (pour les marqueurs).
  const highlightsByTurn = new Map<number, Highlight[]>();
  for (const h of highlights) {
    const arr = highlightsByTurn.get(h.turn) || [];
    arr.push(h);
    highlightsByTurn.set(h.turn, arr);
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700 bg-slate-900/50 p-2">
      <svg width={W} height={H} className="block">
        {/* Grid lines */}
        {Array.from({ length: 5 }, (_, i) => {
          const y = padT + (chartH * i) / 4;
          const val = Math.round(maxValue - (maxValue * i) / 4);
          return (
            <g key={i}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="#1e293b" strokeWidth={1} />
              <text x={padL - 5} y={y + 4} textAnchor="end" fontSize={10} fill="#64748b">{val}</text>
            </g>
          );
        })}

        {/* X-axis labels (tours) */}
        {turns.map(t => (
          <text
            key={t}
            x={xScale(t)}
            y={H - 8}
            textAnchor="middle"
            fontSize={10}
            fill={selectedTurn === t ? "#e2e8f0" : "#64748b"}
            fontWeight={selectedTurn === t ? "bold" : "normal"}
          >
            T{t}
          </text>
        ))}

        {/* Opp line (red/orange) */}
        <path d={oppPath} fill="none" stroke={oppColor} strokeWidth={2} opacity={0.8} />
        {oppPoints.map((p, i) => (
          <circle
            key={`opp-${i}`}
            cx={p.x}
            cy={p.y}
            r={selectedTurn === p.turn ? 5 : 3}
            fill={oppColor}
            onClick={() => onSelectTurn(p.turn)}
            className="cursor-pointer"
          />
        ))}

        {/* Me line (blue/cyan) */}
        <path d={mePath} fill="none" stroke={meColor} strokeWidth={2} opacity={0.8} />
        {mePoints.map((p, i) => (
          <circle
            key={`me-${i}`}
            cx={p.x}
            cy={p.y}
            r={selectedTurn === p.turn ? 5 : 3}
            fill={meColor}
            onClick={() => onSelectTurn(p.turn)}
            className="cursor-pointer"
          />
        ))}

        {/* Highlight markers (triangles en haut) */}
        {turns.map(t => {
          const hs = highlightsByTurn.get(t);
          if (!hs) return null;
          const x = xScale(t);
          return hs.slice(0, 1).map((h, i) => (
            <text
              key={`hl-${t}-${i}`}
              x={x}
              y={padT + 8}
              textAnchor="middle"
              fontSize={12}
              onClick={() => onSelectTurn(t)}
              className="cursor-pointer"
            >
              {h.icon}
            </text>
          ));
        })}

        {/* Selected turn vertical line */}
        {selectedTurn != null && (
          <line
            x1={xScale(selectedTurn)}
            y1={padT}
            x2={xScale(selectedTurn)}
            y2={padT + chartH}
            stroke="#475569"
            strokeWidth={1}
            strokeDasharray="4 2"
          />
        )}
      </svg>

      {/* Legend */}
      <div className="mt-1 flex items-center gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5" style={{ background: meColor }} />
          Toi
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5" style={{ background: oppColor }} />
          Adversaire
        </span>
        <span className="text-slate-600">Clique sur un point pour voir le détail du tour</span>
      </div>
    </div>
  );
}

// --- Helpers ---

function indexByTurn(snapshots: TurnSnapshot[], field: "life" | "hand_count" | "deck_remaining"): { me: Record<number, number>; opp: Record<number, number> } {
  const me: Record<number, number> = {};
  const opp: Record<number, number> = {};
  for (const s of snapshots) {
    const val = s[field];
    if (val != null) {
      if (s.side === "me") me[s.turn] = val;
      else opp[s.turn] = val;
    }
  }
  return { me, opp };
}

function toPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    d += ` L ${points[i].x} ${points[i].y}`;
  }
  return d;
}

function eventLabel(type: string): string {
  const labels: Record<string, string> = {
    deploy: "Déployé",
    attack: "Attaque",
    counter: "Counter",
    counter_event: "Counter!",
  };
  return labels[type] || type;
}
