"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { fetchDeckDetail, fetchMetaCheck } from "@/lib/api";
import type { DeckDetail, MetaCheckResponse } from "@/lib/stats-types";
import { CardImage } from "@/components/Card";
import { MetaCheckPanel } from "@/components/MetaCheckPanel";
import { OpeningOddsPanel } from "@/components/OpeningOddsPanel";
import Link from "next/link";

export default function DeckDetailPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-4 py-4"><p className="text-slate-500">Chargement…</p></div>}>
      <DeckDetailInner />
    </Suspense>
  );
}

function DeckDetailInner() {
  const sp = useSearchParams();
  const name = sp.get("name") || "";
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [metaCheck, setMetaCheck] = useState<MetaCheckResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!name) { setLoading(false); return; }
    setLoading(true);
    Promise.all([fetchDeckDetail(name), fetchMetaCheck(name)]).then(([d, mc]) => {
      setDeck(d);
      setMetaCheck(mc);
      setLoading(false);
    });
  }, [name]);

  if (loading) return <div className="mx-auto max-w-3xl px-4 py-4"><p className="text-slate-500">Chargement…</p></div>;
  if (!deck) return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <Link href="/decks" className="text-blue-400 hover:underline text-sm">← Decks</Link>
      <p className="mt-2 text-amber-400">Deck introuvable.</p>
    </div>
  );

  const s = deck.stats;
  const sortedCards = [...deck.cards].sort((a, b) => a.name.localeCompare(b.name));
  const unknownQty = s.unknown.reduce(
    (n, id) => n + (deck.cards.find((c) => c.card_id === id)?.qty ?? 1),
    0,
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/decks" className="text-blue-400 hover:underline text-sm">← Decks</Link>
        <h1 className="text-xl font-bold">{deck.name}</h1>
      </header>

      <div className="mb-4 flex items-center gap-3">
        <CardImage id={deck.leader} name={deck.leader_name} className="w-16 h-22" />
        <div>
          <div className="text-sm font-semibold text-slate-200">{deck.leader_name}</div>
          <div className="text-xs text-slate-500">{s.total} cartes</div>
        </div>
      </div>

      {s.unknown.length > 0 && (
        <div className="mb-4 rounded border border-amber-700/50 bg-amber-950/40 p-2 text-xs text-amber-300">
          ⚠️ {unknownQty} carte(s) sans données ({s.unknown.join(", ")}) — exclues des stats
          ci-dessous (courbe, counters, couleurs, effets). Les totaux portent donc sur{" "}
          {s.total - unknownQty} cartes.
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatBox label="Counters +1000" value={s.counter_1000} />
        <StatBox label="Counters +2000" value={s.counter_2000} />
        <StatBox label="Effets" value={s.effects_total} />
        <StatBox label="Triggers" value={s.triggers_total} />
      </div>

      <Section title="Courbe de coût">
        <div className="flex items-end gap-1 h-24">
          {Object.entries(s.curve)
            .sort((a, b) => Number(a[0]) - Number(b[0]))
            .map(([cost, count]) => (
              <div key={cost} className="flex flex-col items-center gap-1">
                <span className="text-xs text-slate-400">{count}</span>
                <div
                  className="w-8 rounded bg-blue-600"
                  style={{ height: `${Math.min(100, count * 8)}px` }}
                />
                <span className="text-xs text-slate-500">{cost}</span>
              </div>
            ))}
        </div>
      </Section>

      <Section title="Couleurs">
        <ColorBreakdown colors={s.colors} />
      </Section>

      <Section title="Probabilités d'ouverture (main de 5)">
        <OpeningOddsPanel odds={deck.odds} />
      </Section>

      <Section title={`Cartes (${deck.cards.length})`}>
        <div className="flex flex-wrap gap-1">
          {sortedCards.map((c, i) => (
            <span key={i} className="relative">
              {c.qty > 1 && (
                <span className="absolute -top-1 -right-1 z-10 rounded bg-slate-700 px-1 text-xs text-white">
                  {c.qty}×
                </span>
              )}
              <CardImage id={c.card_id} name={c.name} />
            </span>
          ))}
        </div>
      </Section>

      <Section title="🔍 Meta-Check vs archétype moyen">
        <MetaCheckPanel data={metaCheck} />
      </Section>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-2 text-center">
      <div className="text-lg font-bold text-slate-200">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

function ColorBreakdown({ colors }: { colors: Record<string, number> }) {
  const colorMap: Record<string, string> = {
    Red: "bg-red-600",
    Blue: "bg-blue-600",
    Green: "bg-green-600",
    Yellow: "bg-yellow-600",
    Purple: "bg-purple-600",
    Black: "bg-slate-800",
  };
  return (
    <div className="flex gap-2">
      {Object.entries(colors).map(([color, count]) => (
        <span
          key={color}
          className={`rounded px-2 py-1 text-xs text-white ${colorMap[color] || "bg-slate-600"}`}
        >
          {color} × {count}
        </span>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-300">{title}</h3>
      {children}
    </section>
  );
}
