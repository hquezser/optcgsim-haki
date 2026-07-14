"use client";

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { Suspense, useEffect, useState, useCallback } from "react";
import { fetchStats, fetchStatsFilters } from "@/lib/api";
import type {
  StatsResponse,
  StatsMetasResponse,
  StatsMetaResponse,
  StatsDetailResponse,
  StatsMatchupResponse,
  MatchupRow,
} from "@/lib/stats-types";
import { WinrateBars } from "@/components/WinrateBar";
import { OpeningImpactList, PlayedImpactList, ShrinkageList, CombosList } from "@/components/ImpactLists";
import { CurveChart, AttackDistChart, CounterStatsDisplay, DonWasteDisplay } from "@/components/Charts";
import { MulliganRecoDisplay, HandScoreDisplay } from "@/components/MulliganReco";
import { ValueScorePanel } from "@/components/ValueScorePanel";
import { CardImage } from "@/components/Card";
import { TooltipIcon } from "@/components/Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";
import Link from "next/link";

export default function StatsPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-5xl px-4 py-4"><p className="text-slate-500">Chargement…</p></div>}>
      <StatsPageInner />
    </Suspense>
  );
}

function StatsPageInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const meta = sp.get("meta") || undefined;
  const leader = sp.get("leader") || undefined;
  const opp = sp.get("opp") || undefined;
  const deck = sp.get("deck") || undefined;
  const mode = sp.get("mode") || undefined;
  const fmt = sp.get("format") || undefined;

  const [data, setData] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<{ modes: string[]; formats: string[] } | null>(null);

  useEffect(() => {
    fetchStatsFilters().then(setFilters);
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchStats({ meta, leader, opp, deck, mode, format: fmt }).then((d) => {
      setData(d);
      setLoading(false);
    });
  }, [meta, leader, opp, deck, mode, fmt]);

  const updateFilter = useCallback((key: string, value: string | undefined) => {
    const params = new URLSearchParams(sp.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    router.replace(`${pathname}?${params.toString()}`);
  }, [sp, router, pathname]);

  return (
    <div className="mx-auto max-w-5xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/" className="text-blue-400 hover:underline text-sm">← Live</Link>
        <h1 className="text-xl font-bold">Stats</h1>
        <Link href="/decks" className="ml-auto text-blue-400 hover:underline text-sm">Decks →</Link>
      </header>

      <FilterBar
        filters={filters}
        mode={mode}
        fmt={fmt}
        onChangeMode={(v) => updateFilter("mode", v)}
        onChangeFmt={(v) => updateFilter("format", v)}
      />

      {loading && <p className="text-slate-500">Chargement…</p>}
      {!loading && !data && (
        <p className="text-amber-400">Serveur API injoignable. Lance <code className="bg-slate-800 px-1 rounded">optcgsim-haki dashboard</code></p>
      )}
      {!loading && data && (
        <StatsContent
          data={data}
          meta={meta}
          leader={leader}
          opp={opp}
          deck={deck}
          mode={mode}
          fmt={fmt}
        />
      )}
    </div>
  );
}

function FilterBar({
  filters,
  mode,
  fmt,
  onChangeMode,
  onChangeFmt,
}: {
  filters: { modes: string[]; formats: string[] } | null;
  mode?: string;
  fmt?: string;
  onChangeMode: (v: string | undefined) => void;
  onChangeFmt: (v: string | undefined) => void;
}) {
  if (!filters) return null;
  if (filters.modes.length <= 1 && filters.formats.length <= 1) return null;
  const modeLabel: Record<string, string> = { ranked: "Ranked", direct: "Standard (direct)" };
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-900/50 px-3 py-2">
      <span className="text-xs font-semibold text-slate-400">Filtres</span>
      {filters.modes.length > 1 && (
        <label className="flex items-center gap-1 text-xs text-slate-400">
          Mode
          <select
            value={mode || "all"}
            onChange={(e) => onChangeMode(e.target.value === "all" ? undefined : e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            <option value="all">Tous</option>
            {filters.modes.map((m) => (
              <option key={m} value={m}>{modeLabel[m] || m}</option>
            ))}
          </select>
        </label>
      )}
      {filters.formats.length > 1 && (
        <label className="flex items-center gap-1 text-xs text-slate-400">
          Format
          <select
            value={fmt || "all"}
            onChange={(e) => onChangeFmt(e.target.value === "all" ? undefined : e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            <option value="all">Tous</option>
            {filters.formats.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

function qsSuffix(mode?: string, fmt?: string): string {
  const parts: string[] = [];
  if (mode) parts.push(`mode=${encodeURIComponent(mode)}`);
  if (fmt) parts.push(`format=${encodeURIComponent(fmt)}`);
  return parts.length ? `&${parts.join("&")}` : "";
}

function Breadcrumb({
  meta, leader, opp, deck, mode, fmt,
}: {
  meta?: string; leader?: string; opp?: string; deck?: string;
  mode?: string; fmt?: string;
}) {
  const sfx = qsSuffix(mode, fmt);
  const parts: React.ReactNode[] = [
    <Link key="root" href={`/stats${sfx ? `?${sfx.slice(1)}` : ""}`} className="text-blue-400 hover:underline">Metas</Link>,
  ];
  if (meta) parts.push(<Link key="meta" href={`/stats?meta=${encodeURIComponent(meta)}${sfx}`} className="text-blue-400 hover:underline">{meta}</Link>);
  if (leader) parts.push(<Link key="leader" href={`/stats?meta=${encodeURIComponent(meta!)}&leader=${encodeURIComponent(leader)}${sfx}`} className="text-blue-400 hover:underline">{leader}</Link>);
  if (deck) parts.push(<Link key="deck" href={`/stats?meta=${encodeURIComponent(meta!)}&deck=${encodeURIComponent(deck)}${sfx}`} className="text-blue-400 hover:underline">{deck}</Link>);
  if (opp) parts.push(<span key="opp" className="text-slate-400">vs {opp}</span>);
  return <div className="mb-3 flex items-center gap-1 text-sm text-slate-500">{parts.map((p, i) => <span key={i} className="flex items-center gap-1">{i > 0 && <span className="text-slate-600">›</span>}{p}</span>)}</div>;
}

function StatsContent({
  data, meta, leader, opp, deck, mode, fmt,
}: {
  data: StatsResponse;
  meta?: string;
  leader?: string;
  opp?: string;
  deck?: string;
  mode?: string;
  fmt?: string;
}) {
  if (data.level === "metas") return <MetasView data={data} mode={mode} fmt={fmt} />;
  if (data.level === "meta") return <MetaView data={data} meta={meta!} mode={mode} fmt={fmt} />;
  if (data.level === "detail") return <DetailView data={data} meta={meta!} leader={leader} deck={deck} mode={mode} fmt={fmt} />;
  if (data.level === "matchup") return <MatchupView data={data} meta={meta!} leader={leader} opp={opp} deck={deck} mode={mode} fmt={fmt} />;
  return null;
}

function MetasView({ data, mode, fmt }: { data: StatsMetasResponse; mode?: string; fmt?: string }) {
  const sfx = qsSuffix(mode, fmt);
  return (
    <>
      <h2 className="mb-2 text-lg font-semibold">Stats par meta</h2>
      <WinrateBars
        rows={data.metas}
        linkFn={(r) => `/stats?meta=${encodeURIComponent(r.label)}${sfx}`}
      />
      <p className="mt-3 text-sm text-slate-500">Choisis un meta pour voir le détail par leader et par deck.</p>
    </>
  );
}

function MetaView({ data, meta, mode, fmt }: { data: StatsMetaResponse; meta: string; mode?: string; fmt?: string }) {
  const sfx = qsSuffix(mode, fmt);
  return (
    <>
      <Breadcrumb meta={meta} mode={mode} fmt={fmt} />
      <h2 className="mb-2 text-lg font-semibold">{meta} — Leaders</h2>
      <WinrateBars
        rows={data.leaders}
        linkFn={(r) => `/stats?meta=${encodeURIComponent(meta)}&leader=${encodeURIComponent(r.label)}${sfx}`}
      />
      <h3 className="mt-4 mb-2 text-base font-semibold">
        Par deck (toi)<TooltipIcon text={STATS_TIPS.par_deck} />
      </h3>
      <WinrateBars
        rows={data.decks}
        linkFn={(r) => `/stats?meta=${encodeURIComponent(meta)}&deck=${encodeURIComponent(r.label)}${sfx}`}
      />
    </>
  );
}

function DetailView({
  data, meta, leader, deck, mode, fmt,
}: {
  data: StatsDetailResponse;
  meta: string;
  leader?: string;
  deck?: string;
  mode?: string;
  fmt?: string;
}) {
  const sfx = qsSuffix(mode, fmt);
  const qsBase = deck
    ? `meta=${encodeURIComponent(meta)}&deck=${encodeURIComponent(deck)}`
    : `meta=${encodeURIComponent(meta)}&leader=${encodeURIComponent(leader || "")}`;
  return (
    <>
      <Breadcrumb meta={meta} leader={leader} deck={deck} mode={mode} fmt={fmt} />
      <div className="mb-3 flex items-center gap-3">
        {data.leader_id && <CardImage id={data.leader_id} name={data.label} className="w-16 h-22" />}
        <h2 className="text-lg font-semibold">{data.label} — {meta}</h2>
      </div>

      <Section title="Premier / Second" tip={STATS_TIPS.premier_second}>
        <WinrateBars rows={data.splits.first_second} />
      </Section>
      <Section title="Mulligan" tip={STATS_TIPS.mulligan_split}>
        <WinrateBars rows={data.splits.mulligan} />
      </Section>
      <Section title="Écart d'Elo (favori vs underdog)" tip={STATS_TIPS.elo_gap}>
        <WinrateBars rows={data.splits.elo_gap} />
      </Section>
      <Section title="Matchups (clic pour le détail)" tip={STATS_TIPS.matchups}>
        {data.matchups.length === 0 ? (
          <p className="text-slate-500 text-sm">—</p>
        ) : (
          <div>
            {data.matchups.map((m, i) => (
              <MatchupRow key={i} row={m} href={`/stats?${qsBase}&opp=${encodeURIComponent(m.opp_id)}${sfx}`} />
            ))}
          </div>
        )}
      </Section>
      <Section title={`Main de départ — lift brut (n≥15, baseline ${data.opening_impact.baseline_wr ?? "?"}%, n=${data.opening_impact.n})`} tip={STATS_TIPS.lift_brut}>
        <OpeningImpactList cards={data.opening_impact.cards} />
      </Section>
      <Section title="Cartes posées — lift conditionné par phase (n≥5)" tip={STATS_TIPS.lift_phase}>
        <PlayedImpactList cards={data.played_impact} />
      </Section>
      <Section title="🔗 Combos gagnants (cartes posées ensemble)" tip={STATS_TIPS.combos}>
        <CombosList combos={data.winning_combos} />
      </Section>
      <Section title="❤️ Courbe de vie par tour" tip={STATS_TIPS.curve_life}>
        <CurveChart data={data.life_trajectory} ylabel="Life" />
      </Section>
      <Section title="🃏 Courbe DON!! (coût moyen déployé)" tip={STATS_TIPS.curve_don}>
        <CurveChart data={data.deploy_curve} ylabel="Coût" />
      </Section>
      <Section title="⚔️ Pression Leader vs Board" tip={STATS_TIPS.pression}>
        <AttackDistChart data={data.attack_distribution} />
      </Section>
      <Section title="🛡️ Usage des counters" tip={STATS_TIPS.counters}>
        <CounterStatsDisplay data={data.counter_stats} />
      </Section>
      <Section title="⬡ DON Waste (DON disponible non utilisé)" tip={STATS_TIPS.don_waste}>
        <DonWasteDisplay data={data.don_waste} />
      </Section>
      {/* Value Score : rendu uniquement si présent et non vide (backend l'omet quand le flag est OFF). */}
      {data.value_scores && data.value_scores.length > 0 && (
        <Section title="💎 Value Score (impact réel par carte)" tip={STATS_TIPS.value_score}>
          <ValueScorePanel cards={data.value_scores} />
        </Section>
      )}
    </>
  );
}

function MatchupView({
  data, meta, leader, opp, deck, mode, fmt,
}: {
  data: StatsMatchupResponse;
  meta: string;
  leader?: string;
  opp?: string;
  deck?: string;
  mode?: string;
  fmt?: string;
}) {
  return (
    <>
      <Breadcrumb meta={meta} leader={leader} opp={opp} deck={deck} mode={mode} fmt={fmt} />
      <div className="mb-3 flex items-center gap-3">
        {data.leader_id && <CardImage id={data.leader_id} name={data.label} className="w-16 h-22" />}
        {opp && <CardImage id={opp} name={data.opp_name} className="w-12 h-17" />}
        <h2 className="text-lg font-semibold">{data.label} vs {data.opp_name}</h2>
      </div>
      <p className="mb-3 text-sm text-slate-500">{meta} · {data.head}</p>

      <Section title="🎯 Reco mulligan" tip={STATS_TIPS.reco_mu}>
        <MulliganRecoDisplay reco={data.mulligan_reco} />
      </Section>
      <HandScoreDisplay hss={data.hand_score_stats} />
      <Section title="Ouverture — classement shrinkage" tip={STATS_TIPS.shrinkage}>
        <ShrinkageList scored={data.mulligan_reco.scored} />
      </Section>
      <Section title="Premier / Second (ce matchup)" tip={STATS_TIPS.premier_second}>
        <WinrateBars rows={data.splits.first_second} />
      </Section>
      <Section title="Écart d'Elo (favori vs underdog)" tip={STATS_TIPS.elo_gap}>
        <WinrateBars rows={data.splits.elo_gap} />
      </Section>
      <Section title="Cartes posées — lift conditionné par phase (n≥5)" tip={STATS_TIPS.lift_phase}>
        <PlayedImpactList cards={data.played_impact} />
      </Section>
      <Section title="❤️ Courbe de vie par tour" tip={STATS_TIPS.curve_life}>
        <CurveChart data={data.life_trajectory} ylabel="Life" />
      </Section>
      <Section title="🃏 Courbe DON!! (coût moyen déployé)" tip={STATS_TIPS.curve_don}>
        <CurveChart data={data.deploy_curve} ylabel="Coût" />
      </Section>
      <Section title="⚔️ Pression Leader vs Board" tip={STATS_TIPS.pression}>
        <AttackDistChart data={data.attack_distribution} />
      </Section>
      <Section title="🛡️ Usage des counters" tip={STATS_TIPS.counters}>
        <CounterStatsDisplay data={data.counter_stats} />
      </Section>
      <Section title="⬡ DON Waste (DON disponible non utilisé)" tip={STATS_TIPS.don_waste}>
        <DonWasteDisplay data={data.don_waste} />
      </Section>
    </>
  );
}

function MatchupRow({ row, href }: { row: MatchupRow; href: string }) {
  const pct = row.winrate;
  const cls = pct >= 50 ? "bg-green-600" : "bg-red-600";
  return (
    <Link href={href} className="block">
      <div className="flex items-center gap-2 py-1 border-b border-slate-800 hover:bg-slate-900/50">
        <span className="w-48 truncate text-sm text-slate-300">{row.name}</span>
        <span className="flex-1 rounded bg-slate-900 h-3.5 overflow-hidden">
          <span className={`block h-full ${cls}`} style={{ width: `${pct}%` }} />
        </span>
        <span className="w-24 text-right text-sm tabular-nums text-slate-400">
          {pct.toFixed(0)}% <span className="text-slate-600">({row.wins}-{row.losses})</span>
        </span>
      </div>
    </Link>
  );
}

function Section({ title, tip, children }: { title: string; tip?: string; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-300">
        {title}
        {tip && <TooltipIcon text={tip} />}
      </h3>
      {children}
    </section>
  );
}
