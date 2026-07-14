"use client";

import type { DefenseState, PlayerState } from "@/lib/types";

function k(v: number): string {
  return v >= 1000 ? `${v / 1000}k` : `${v}`;
}

/** Panneau « Ma défense » — 100 % exact/public, pensé pour l'overlay.
 *
 *  Inputs : ma vie/counters/blockers (mes snapshots = vérité) face au board adverse VISIBLE
 *  (powers publics + DON comptés). Ne spécule pas sur la main adverse : si le board visible
 *  suffit à me tuer, alerte ; sinon on donne les ressources et le pris-en-compte.
 */
export function DefensePanel({
  defense,
  opp,
}: {
  defense: DefenseState;
  opp?: PlayerState | null;
}) {
  const spent = opp?.counters_spent;
  return (
    <section>
      <div className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold">
        🛡️ Ma défense
        {defense.opp_can_lethal && (
          <span className="rounded bg-red-900/70 px-1 font-semibold text-red-300">
            ⚠️ lethal au board visible — {defense.lives_at_risk}/{defense.my_life ?? "?"} vies
          </span>
        )}
        {!defense.opp_can_lethal && (defense.lives_at_risk ?? 0) > 0 && (
          <span className="font-normal text-slate-400">
            {defense.lives_at_risk}/{defense.my_life ?? "?"} vies exposées au board
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 text-[11px] tabular-nums">
        <span className="text-slate-200" title="Somme des counters de MA main (exacte)">
          ✋ {k(defense.my_counter_pool)} counter
        </span>
        <span className="text-slate-200" title="Mes blockers posés">
          🛡 {defense.my_blockers} blocker{defense.my_blockers > 1 ? "s" : ""}
        </span>
        <span
          className="ml-auto text-slate-400"
          title={defense.opp_leader_known
            ? "Attaquants adverses visibles (board + leader) et leurs DON"
            : "Board adverse visible — leader pas encore identifié, non compté"}
        >
          {defense.opp_attacks != null ? (
            <>
              ADV : {defense.opp_attacks} atk
              {defense.opp_power != null && ` · Σ ${k(defense.opp_power)}`}
              {!defense.opp_leader_known && " (+ leader ?)"}
              {defense.opp_don > 0 && ` · ${defense.opp_don}⬡`}
            </>
          ) : (
            "ADV : board vide"
          )}
        </span>
      </div>
      {spent && spent.count > 0 && (
        <div
          className="mt-0.5 text-[11px] text-slate-400"
          title="Counters défaussés par l'adversaire (événements publics du log)"
        >
          ADV a brûlé {spent.count} counter{spent.count > 1 ? "s" : ""}
          {spent.total > 0 && ` (${k(spent.total)})`} ce match
        </div>
      )}
    </section>
  );
}
