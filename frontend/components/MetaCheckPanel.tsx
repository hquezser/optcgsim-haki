"use client";

import type { MetaCheckResponse, MetaCheckCard } from "@/lib/stats-types";
import { CardImage } from "./Card";

export function MetaCheckPanel({ data }: { data: MetaCheckResponse | null }) {
  if (!data) return null;
  if (data.n_historical === 0) {
    return (
      <p className="text-sm text-slate-500">
        Aucun deck historique pour ce leader — le meta-check n'est pas disponible.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Comparaison à l'archétype moyen de {data.leader_name} ({data.n_historical} decks
        historiques). Les staples sont les cartes à ≥50% de présence dans la meta.
      </p>

      {data.staples_missing.length > 0 && (
        <CardList
          title="⚠️ Staples manquantes"
          subtitle="Cartes présentes dans la meta mais absentes de ton deck"
          cards={data.staples_missing}
          variant="warning"
          showPresence
        />
      )}

      {data.underperforming.length > 0 && (
        <CardList
          title="📉 Cartes sous-performantes"
          subtitle="Cartes de ton deck avec un lift négatif (corrélées aux défaites)"
          cards={data.underperforming}
          variant="danger"
          showLift
        />
      )}

      {data.extra_cards.length > 0 && (
        <CardList
          title="🎯 Tech picks"
          subtitle="Cartes de ton deck rares dans la meta (&lt;25% de présence)"
          cards={data.extra_cards}
          variant="info"
          showPresence
        />
      )}

      {data.top_performers.length > 0 && (
        <CardList
          title="⭐ Top performers"
          subtitle="Cartes de ton deck avec un lift positif (corrélées aux victoires)"
          cards={data.top_performers}
          variant="success"
          showLift
        />
      )}

      {data.staples_present.length > 0 && (
        <CardList
          title="✓ Staples présentes"
          subtitle="Cartes meta bien intégrées dans ton deck"
          cards={data.staples_present}
          variant="success"
          showPresence
        />
      )}

      {data.staples_missing.length === 0 &&
        data.underperforming.length === 0 &&
        data.extra_cards.length === 0 && (
          <p className="text-sm text-slate-400">
            ✓ Ton deck correspond bien à l'archétype moyen de la meta.
          </p>
        )}
    </div>
  );
}

function CardList({
  title,
  subtitle,
  cards,
  variant,
  showPresence,
  showLift,
}: {
  title: string;
  subtitle: string;
  cards: MetaCheckCard[];
  variant: "warning" | "danger" | "info" | "success";
  showPresence?: boolean;
  showLift?: boolean;
}) {
  const titleCls = {
    warning: "text-amber-400",
    danger: "text-red-400",
    info: "text-blue-400",
    success: "text-green-400",
  }[variant];

  return (
    <div>
      <h4 className={`text-sm font-semibold ${titleCls}`}>{title}</h4>
      <p className="mb-2 text-xs text-slate-600" dangerouslySetInnerHTML={{ __html: subtitle }} />
      <div className="flex flex-wrap gap-2">
        {cards.map((c) => (
          <div key={c.card_id} className="flex items-center gap-2 rounded border border-slate-800 bg-slate-900/50 p-2">
            <CardImage id={c.card_id} name={c.name} className="w-12 h-17" />
            <div className="text-xs">
              <div className="text-slate-300">{c.name}</div>
              {c.cost != null && <div className="text-slate-500">⬡ {c.cost}</div>}
              {showPresence && c.presence != null && (
                <div className="text-amber-400">{c.presence.toFixed(0)}% meta</div>
              )}
              {showLift && c.lift != null && (
                <div className={c.lift >= 0 ? "text-green-400" : "text-red-400"}>
                  {c.lift >= 0 ? "+" : ""}{c.lift.toFixed(0)}% lift
                </div>
              )}
              {c.n != null && <div className="text-slate-600">n={c.n}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
