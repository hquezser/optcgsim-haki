"use client";

import { useEffect, useState } from "react";
import { fetchDecks } from "@/lib/api";
import type { DeckSummary } from "@/lib/stats-types";
import Link from "next/link";

export default function DecksPage() {
  const [decks, setDecks] = useState<DeckSummary[] | null>(null);

  useEffect(() => {
    fetchDecks().then(setDecks);
  }, []);

  return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/" className="text-blue-400 hover:underline text-sm">← Live</Link>
        <h1 className="text-xl font-bold">Decks</h1>
        <Link href="/stats" className="ml-auto text-blue-400 hover:underline text-sm">Stats →</Link>
      </header>

      {decks === null && <p className="text-slate-500">Chargement…</p>}
      {decks !== null && decks.length === 0 && (
        <p className="text-slate-500 text-sm">
          Aucun deck trouvé. Les fichiers <code className="bg-slate-800 px-1 rounded">.txt</code> de deck
          doivent être dans le dossier app-support d'OPTCGSim.
        </p>
      )}
      {decks && decks.length > 0 && (
        <div className="space-y-1">
          {decks.map((d) => (
            <Link
              key={d.name}
              href={`/decks/detail?name=${encodeURIComponent(d.name)}`}
              className="block rounded border border-slate-800 bg-slate-900/50 p-3 hover:border-slate-600"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-slate-200">{d.name}</span>
                {d.leader_name && <span className="text-sm text-slate-400">{d.leader_name}</span>}
                {d.total != null && <span className="text-xs text-slate-500">{d.total} cartes</span>}
                {d.counter_1000 != null && d.counter_1000 > 0 && (
                  <span className="rounded bg-slate-800 px-1.5 text-xs text-slate-400">
                    +1000 × {d.counter_1000}
                  </span>
                )}
                {d.counter_2000 != null && d.counter_2000 > 0 && (
                  <span className="rounded bg-slate-800 px-1.5 text-xs text-slate-400">
                    +2000 × {d.counter_2000}
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
