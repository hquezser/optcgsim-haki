"use client";

import { useEffect, useState } from "react";
import { fetchMatches } from "@/lib/api";
import type { MatchSummary } from "@/lib/match-types";
import { CardImage } from "@/components/Card";
import Link from "next/link";

export default function MatchesPage() {
  const [matches, setMatches] = useState<MatchSummary[] | null>(null);

  useEffect(() => {
    fetchMatches(30).then(setMatches);
  }, []);

  return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/" className="text-blue-400 hover:underline text-sm">← Live</Link>
        <h1 className="text-xl font-bold">Parties récentes</h1>
      </header>

      {!matches && (
        <div className="text-slate-500">Chargement…</div>
      )}

      {matches && matches.length === 0 && (
        <div className="rounded border border-slate-700 bg-slate-900 p-6 text-center text-slate-500">
          Aucune partie enregistrée. Joue une partie dans OPTCGSim pour voir la timeline.
        </div>
      )}

      {matches && matches.length > 0 && (
        <div className="space-y-1">
          {matches.map((m) => (
            <Link
              key={m.id}
              href={`/matches/detail?id=${encodeURIComponent(m.id)}`}
              className="flex items-center gap-3 rounded border border-slate-800 bg-slate-900/50 p-3 hover:border-slate-600"
            >
              <div className="flex items-center gap-2">
                {m.my_leader && <CardImage id={m.my_leader} name={m.my_leader_name} />}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-200">
                    {m.my_leader_name || "?"}
                  </span>
                  <span className="text-xs text-slate-600">vs</span>
                  <span className="text-sm text-slate-300">
                    {m.opp_leader_name || "?"}
                  </span>
                </div>
                <div className="text-xs text-slate-500">
                  {m.played_at ? new Date(m.played_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "?"}
                  {m.meta && ` · ${m.meta}`}
                  {m.duration_s != null && ` · ${Math.round(m.duration_s)}s`}
                </div>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                m.result === "win" ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"
              }`}>
                {m.result === "win" ? "W" : "L"}
              </span>
              {m.opp_leader && <CardImage id={m.opp_leader} name={m.opp_leader_name} />}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
