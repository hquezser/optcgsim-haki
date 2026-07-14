"use client";

import type { LiveState, Lethal, TriggerRisk, CounterAnalysis } from "@/lib/types";

/**
 * CoachAlerts — synthèse anti-surcharge visuelle.
 *
 * N'affiche QUE les alertes actionnables au moment présent :
 * - Lethal risk (déjà conditionnel dans LethalPanel, repris ici en compact)
 * - Trigger risk élevé (≥30%) OU adversaire à ≤2 vies (chaque life flip compte)
 * - Counters +2000 encore attendus (au moins 2 non défaussés)
 * - Menace T+1 avec score ≥40% (carte très probablement jouée ce tour)
 * - Score de main mauvais (Mulligan)
 *
 * Si aucune alerte → message rassurant "Situation sous contrôle".
 * Les détails restent accessibles dans les panneaux détaillés (collapsibles).
 */

interface Alert {
  level: "critical" | "warning" | "info";
  icon: string;
  text: string;
  detail?: string;
}

const LEVEL_STYLES: Record<Alert["level"], string> = {
  critical: "border-red-700 bg-red-950/40 text-red-300",
  warning: "border-amber-700 bg-amber-950/30 text-amber-300",
  info: "border-blue-700 bg-blue-950/30 text-blue-300",
};

export function CoachAlerts({ data }: { data: LiveState }) {
  const alerts = buildAlerts(data);

  if (alerts.length === 0) {
    return (
      <div className="rounded-lg border border-green-800/50 bg-green-950/20 p-2 text-center text-sm text-green-400">
        ✅ Situation sous contrôle — aucune alerte critique.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {alerts.map((a, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${LEVEL_STYLES[a.level]}`}
        >
          <span className="text-lg leading-none">{a.icon}</span>
          <div>
            <span className="font-semibold">{a.text}</span>
            {a.detail && <span className="ml-1 text-xs opacity-80">{a.detail}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function buildAlerts(data: LiveState): Alert[] {
  const alerts: Alert[] = [];
  const oppLife = data.opp?.life;
  const myLife = data.me?.life;

  // 1. Lethal — critique, toujours affiché si actif.
  if (data.lethal) {
    const l = data.lethal;
    if (l.opp_can_lethal) {
      alerts.push({
        level: "critical",
        icon: "☠️",
        text: `LETHAL ADVERSE — ${l.lives_at_risk}/${l.my_life} vies en danger`,
        detail: `${l.opp_attacks} attaques • ${l.opp_power?.toLocaleString()} power • tu as ${l.my_blockers} blockers + ${l.my_counter_pool.toLocaleString()} counters`,
      });
    }
    if (l.me_can_lethal) {
      alerts.push({
        level: "critical",
        icon: "🎯",
        text: `LETHAL CE TOUR — ${l.lives_i_can_deal}/${l.opp_life} vies à infliger`,
        detail: `${l.me_attacks} attaques • ${l.me_power?.toLocaleString()} power • adverse a ${l.opp_blockers} blockers`,
      });
    }
  }

  // 2. Trigger risk — alerte si ≥30% OU si adversaire à ≤2 vies (chaque flip compte).
  if (data.trigger_risk && data.trigger_risk.pct != null) {
    const tr = data.trigger_risk;
    const lowLife = oppLife != null && oppLife <= 2;
    if (tr.pct >= 30 || (lowLife && tr.pct >= 15)) {
      alerts.push({
        level: tr.pct >= 50 ? "critical" : "warning",
        icon: "⚡",
        text: `Trigger risk ${tr.pct}%`,
        detail: lowLife
          ? `adversaire à ${oppLife} life — chaque flip peut sauver/sanctionner`
          : `${tr.remaining} triggers restants sur ${tr.unknown} cartes inconnues`,
      });
    }
  }

  // 3. Counters +2000 encore attendus — alerte si ≥2 non défaussés.
  if (data.counter_analysis) {
    const ca = data.counter_analysis;
    const remaining = (ca.plus2k_expected ?? 0) - (ca.plus2k_in_trash ?? 0);
    if (remaining >= 2) {
      alerts.push({
        level: "warning",
        icon: "🛡️",
        text: `${remaining} counters +2000 encore attendus`,
        detail: `${ca.plus2k_in_trash} défaussés / ~${ca.plus2k_expected} estimés — attention aux clashes`,
      });
    }
  }

  // 4. Menace T+1 avec score élevé (≥40%).
  if (data.next_plays && data.next_plays.length > 0) {
    const top = data.next_plays[0];
    if (top.prob >= 40) {
      const phaseLabel = data.next_plays_phase
        ? ` (${data.next_plays_phase})`
        : "";
      alerts.push({
        level: "warning",
        icon: "🎯",
        text: `Menace T+1 : ${top.name} (${top.prob}%)${phaseLabel}`,
        detail: `coût ${top.cost}⬡${
          top.play_rate != null ? ` · play-rate ${top.play_rate}%` : ""
        }`,
      });
    }
  }

  // 5. Score de main mauvais (Mulligan).
  if (data.hand_score && data.hand_score.verdict === "Mulligan") {
    alerts.push({
      level: "warning",
      icon: "🎲",
      text: `Main de départ faible (${data.hand_score.score})`,
      detail: "Mulligan recommandé",
    });
  }

  // 6. Adversaire à 1 life — opportunité critique.
  if (oppLife === 1) {
    alerts.push({
      level: "critical",
      icon: "🔥",
      text: "Adversaire à 1 life — pousse pour le kill",
      detail: "chaque attaque non bloquée gagne la partie",
    });
  }

  // 7. Je suis à 1-2 life — danger critique.
  if (myLife != null && myLife <= 2) {
    alerts.push({
      level: myLife === 1 ? "critical" : "warning",
      icon: "❤️",
      text: `Tu n'as plus que ${myLife} life${myLife === 1 ? "" : "s"}`,
      detail: "joue défensivement — bloque et conserve tes counters",
    });
  }

  return alerts;
}
