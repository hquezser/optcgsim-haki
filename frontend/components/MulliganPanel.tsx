"use client";

import type { HandScore } from "@/lib/types";

/** Aide au mulligan (décision du tour 0), pensée pour l'overlay.
 *
 *  Signal décisif unique : garder / mulligan, dérivé du score de la main de départ comparé
 *  à la moyenne du deck (modèle shrinkage sur l'historique). Affiché UNIQUEMENT pendant la
 *  fenêtre de mulligan (avant tout jeu sur le board).
 */
export function MulliganPanel({ hand }: { hand: HandScore }) {
  const v = hand.verdict;
  const cls =
    v === "Garder" ? "bg-green-900/70 text-green-300"
    : v === "Mulligan" ? "bg-red-900/70 text-red-300"
    : "bg-slate-700 text-slate-300";
  const icon = v === "Garder" ? "✅" : v === "Mulligan" ? "🔄" : "•";
  const delta =
    hand.avg_hand_score != null
      ? ` (${hand.score >= hand.avg_hand_score ? "+" : ""}${(hand.score - hand.avg_hand_score).toFixed(0)} vs deck)`
      : "";
  return (
    <section className="flex items-center gap-2 text-[11px]">
      <span className="font-semibold">🃏 Mulligan</span>
      <span className={`rounded px-1.5 py-0.5 font-semibold ${cls}`}>
        {icon} {v}
      </span>
      <span
        className="text-slate-400 tabular-nums"
        title="Score de la main de départ (modèle shrinkage) vs moyenne du deck"
      >
        score {hand.score > 0 ? "+" : ""}{hand.score}
        {delta}
      </span>
    </section>
  );
}
