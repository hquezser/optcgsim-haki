"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { fetchMatchTimeline } from "@/lib/api";
import type { MatchTimeline } from "@/lib/match-types";
import { MatchTimelineView } from "@/components/MatchTimelineView";
import Link from "next/link";

export default function MatchDetailPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-4 py-4"><p className="text-slate-500">Chargement…</p></div>}>
      <MatchDetailInner />
    </Suspense>
  );
}

function MatchDetailInner() {
  const sp = useSearchParams();
  const matchId = sp.get("id") || "";
  const [data, setData] = useState<MatchTimeline | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!matchId) { setLoading(false); return; }
    setLoading(true);
    fetchMatchTimeline(matchId).then((d) => {
      setData(d);
      setLoading(false);
    });
  }, [matchId]);

  if (loading) return <div className="mx-auto max-w-3xl px-4 py-4"><p className="text-slate-500">Chargement…</p></div>;
  if (!data) return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <Link href="/matches" className="text-blue-400 hover:underline text-sm">← Matches</Link>
      <p className="mt-2 text-amber-400">Partie introuvable ou données de timeline manquantes.</p>
    </div>
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/matches" className="text-blue-400 hover:underline text-sm">← Matches</Link>
        <h1 className="text-xl font-bold">Timeline post-match</h1>
      </header>
      <MatchTimelineView data={data} />
    </div>
  );
}
