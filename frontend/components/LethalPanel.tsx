"use client";

import type { Lethal, LethalConfidence, AttackPlanStep } from "@/lib/types";
import { TooltipIcon } from "./Tooltip";
import { STATS_TIPS } from "@/lib/stats-tips";

const CONF_LABEL = { high: "confiance élevée", medium: "confiance moyenne", low: "confiance faible" } as const;

function ConfChip({ level }: { level: LethalConfidence["level"] }) {
  const cls = level === "high" ? "bg-green-900 text-green-300"
    : level === "medium" ? "bg-amber-900 text-amber-300"
    : "bg-slate-700 text-slate-300";
  return <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>{CONF_LABEL[level]}</span>;
}

function Factors({ conf }: { conf?: LethalConfidence | null }) {
  if (!conf?.factors?.length) return null;
  return <div className="mt-1 text-[11px] text-slate-500">Hypothèses : {conf.factors.join(" · ")}</div>;
}

export function LethalPanel({
  lethal,
  compact = false,
}: {
  lethal?: Lethal;
  /** Overlay : bannière + plan d'attaque seulement (pas les boîtes de score ni le titre). */
  compact?: boolean;
}) {
  if (!lethal) return null;

  // --- Bannière principale : confiance GRADUÉE plutôt qu'un binaire trompeur. Un lethal
  // offensif empile des inférences (counters/vie/leader adverses cachés ou déduits). ---
  const dc = lethal.opp_lethal_confidence;
  const mc = lethal.me_lethal_confidence;
  let banner = null;
  if (lethal.opp_can_lethal) {
    const lvl = dc?.level ?? "medium";
    banner = (
      <div className={`mb-2 rounded border border-red-800 bg-gradient-to-r from-red-950 to-slate-950 p-2 text-center text-sm font-semibold text-red-400 ${lvl !== "low" ? "animate-pulse" : ""}`}>
        ⚠️ Lethal adverse {lvl === "medium" ? "possible" : "à surveiller"} — {lethal.lives_at_risk}/{lethal.my_life} life en danger
        {dc && <ConfChip level={lvl} />}
      </div>
    );
  } else if (lethal.me_can_lethal) {
    const lvl = mc?.level ?? "medium";
    const prob = lethal.me_lethal_prob;
    const k = (v: number) => (v >= 1000 ? `${v / 1000}k` : `${v}`);
    // Modèle « pire cas 2K » : l'annonce fiable est le lethal GARANTI (tient même si chaque
    // carte en main adverse est un counter 2K). Sinon, fait conditionnel exact : le seuil.
    const guaranteed = lethal.me_lethal_guaranteed;
    const worst = lethal.opp_counter_worst;
    // DON!! ouverts adverses -> events de défense possibles (peuvent dépasser le pire cas 2K).
    const oppDon = lethal.opp_don_available;
    const head = guaranteed ? "🎯 Lethal GARANTI ce tour" : "🎯 Lethal possible";
    const cls = guaranteed
      ? "border-green-800 from-green-950 to-slate-950 text-green-400"
      : "border-amber-800 from-amber-950 to-slate-950 text-amber-300";
    banner = (
      <div className={`mb-2 rounded border bg-gradient-to-r p-2 text-center text-sm font-semibold ${cls}`}>
        {head}
        {guaranteed && worst != null && (
          <span className="font-normal"> — tient même à {k(worst)} de counter adverse</span>
        )}
        {!guaranteed && lethal.me_counter_threshold != null && (
          <span className="font-normal">
            {" "}— tient si counters adverses ≤ {k(lethal.me_counter_threshold)}
            {worst != null && <span className="text-slate-400"> (pire cas {k(worst)})</span>}
          </span>
        )}
        {oppDon > 0 && (
          <span className="ml-1 block text-xs font-normal text-amber-400">
            ⚠ {oppDon} DON ouverts → event de défense possible
          </span>
        )}
        {/* Le % de lethal (trigger inclus) est probabiliste : réservé au dashboard. */}
        {prob != null && prob < 100 && !compact && (
          <span className="ml-1 font-normal text-amber-400">· {prob}% (trigger {lethal.trigger_risk_pct ?? "?"}%)</span>
        )}
        {mc && !compact && <ConfChip level={lvl} />}
      </div>
    );
  }

  if (compact) {
    return (
      <section>
        {banner}
        {lethal.me_can_lethal && lethal.me_attack_plan && lethal.me_attack_plan.length > 0 && (
          <AttackPlanView
            plan={lethal.me_attack_plan}
            donAvailable={lethal.me_don_available}
            donNeeded={lethal.me_don_needed}
            lethalProb={null}
            reason={lethal.me_lethal_reason}
            isLethal={lethal.me_can_lethal}
            side="me"
          />
        )}
        {lethal.opp_can_lethal && lethal.opp_attack_plan && lethal.opp_attack_plan.length > 0 && (
          <AttackPlanView
            plan={lethal.opp_attack_plan}
            donAvailable={lethal.opp_don_available}
            donNeeded={lethal.opp_don_needed}
            lethalProb={null}
            reason={lethal.opp_lethal_reason}
            isLethal={lethal.opp_can_lethal}
            side="opp"
          />
        )}
      </section>
    );
  }

  const oppPwr = lethal.opp_power != null ? lethal.opp_power.toLocaleString() : "?";
  const mePwr = lethal.me_power != null ? lethal.me_power.toLocaleString() : "?";
  const oppAtk = lethal.opp_attacks != null ? lethal.opp_attacks : "?";
  const meAtk = lethal.me_attacks != null ? lethal.me_attacks : "?";
  const dangerCls = lethal.opp_can_lethal
    ? "border-red-800 bg-gradient-to-br from-red-950/50 to-slate-900"
    : "border-slate-700 bg-slate-900";
  const oppCls = lethal.me_can_lethal && mc?.level !== "low"
    ? "border-green-800 bg-gradient-to-br from-green-950/50 to-slate-900"
    : "border-slate-700 bg-slate-900";

  return (
    <section className="rounded-lg border border-slate-700 p-3">
      <h2 className="mb-2 flex items-center gap-1 text-sm font-semibold">
        ⚔️ Lethal Risk<TooltipIcon text={STATS_TIPS.lethal} />
      </h2>
      {banner}
      <div className="flex gap-2">
        <div className={`flex-1 rounded-lg border p-2 ${dangerCls}`}>
          <div className="mb-1 text-xs uppercase tracking-wide text-red-400">Danger adverse</div>
          <div className="text-2xl font-bold text-red-400">
            {lethal.lives_at_risk}/{lethal.my_life ?? "?"}
          </div>
          <div className="mt-1 text-xs text-slate-400">
            <b className="text-slate-200">{oppPwr}</b> power • <b className="text-slate-200">{oppAtk}</b> attaques
            <br />
            Mes défenses : <b className="text-slate-200">{lethal.my_blockers}</b> blockers • <b className="text-slate-200">{lethal.my_counter_pool.toLocaleString()}</b> counters
          </div>
          {lethal.opp_can_lethal && <Factors conf={dc} />}
        </div>
        <div className={`flex-1 rounded-lg border p-2 ${oppCls}`}>
          <div className="mb-1 text-xs uppercase tracking-wide text-green-400">Mon opportunité</div>
          <div className="text-2xl font-bold text-green-400">
            {lethal.lives_i_can_deal}/{lethal.opp_life ?? "?"}
          </div>
          <div className="mt-1 text-xs text-slate-400">
            <b className="text-slate-200">{mePwr}</b> power • <b className="text-slate-200">{meAtk}</b> attaques
            <br />
            Défense adverse : <b className="text-slate-200">{lethal.opp_blockers}</b> blockers • <b className="text-slate-200">{lethal.opp_counter_est.toLocaleString()}</b> counters (est.)
          </div>
          {lethal.me_can_lethal && <Factors conf={mc} />}
        </div>
      </div>

      {/* --- Plan d'attaque détaillé (solveur) --- */}
      {lethal.me_attack_plan && lethal.me_attack_plan.length > 0 && (
        <AttackPlanView
          plan={lethal.me_attack_plan}
          donAvailable={lethal.me_don_available}
          donNeeded={lethal.me_don_needed}
          lethalProb={lethal.me_lethal_prob}
          reason={lethal.me_lethal_reason}
          isLethal={lethal.me_can_lethal}
          side="me"
        />
      )}

      {/* --- Plan d'attaque adverse (si danger) --- */}
      {lethal.opp_can_lethal && lethal.opp_attack_plan && lethal.opp_attack_plan.length > 0 && (
        <AttackPlanView
          plan={lethal.opp_attack_plan}
          donAvailable={lethal.opp_don_available}
          donNeeded={lethal.opp_don_needed}
          lethalProb={null}
          reason={lethal.opp_lethal_reason}
          isLethal={lethal.opp_can_lethal}
          side="opp"
        />
      )}
    </section>
  );
}

function AttackPlanView({
  plan,
  donAvailable,
  donNeeded,
  lethalProb,
  reason,
  isLethal,
  side,
}: {
  plan: AttackPlanStep[];
  donAvailable: number;
  donNeeded: number | null;
  lethalProb: number | null;
  reason: string | null;
  isLethal: boolean;
  side: "me" | "opp";
}) {
  const isMe = side === "me";
  const title = isMe ? "🎯 Plan d'attaque optimal" : "☠️ Plan d'attaque adverse estimé";
  const titleCls = isMe ? "text-green-400" : "text-red-400";

  return (
    <div className="mt-2 rounded border border-slate-700 bg-slate-900/50 p-2">
      <div className={`mb-1 text-xs font-semibold ${titleCls}`}>{title}</div>

      {/* Jauge de probabilité */}
      {lethalProb != null && (
        <div className="mb-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400">Probabilité de lethal</span>
            <span className={`font-bold ${
              lethalProb >= 80 ? "text-green-400"
              : lethalProb >= 50 ? "text-amber-400"
              : "text-orange-400"
            }`}>
              {lethalProb}%
            </span>
          </div>
          <div className="mt-0.5 h-2 overflow-hidden rounded bg-slate-800">
            <div
              className={`h-full ${
                lethalProb >= 80 ? "bg-green-600"
                : lethalProb >= 50 ? "bg-amber-600"
                : "bg-orange-600"
              }`}
              style={{ width: `${lethalProb}%` }}
            />
          </div>
        </div>
      )}

      {/* DON summary */}
      {donNeeded != null && (
        <div className="mb-1 text-xs text-slate-400">
          DON!! : <b className={donNeeded <= donAvailable ? "text-green-400" : "text-red-400"}>
            {donNeeded} requis
          </b> / {donAvailable} disponibles
          {donNeeded > donAvailable && (
            <span className="ml-1 text-red-400">(manque {donNeeded - donAvailable})</span>
          )}
        </div>
      )}

      {/* Étapes du plan */}
      <div className="space-y-0.5">
        {plan.map((step, i) => {
          const roleLabel = step.role === "coup_de_grace"
            ? "coup de grâce"
            : step.role === "blocker"
            ? "sur blocker"
            : "sur vie";
          const roleCls = step.role === "coup_de_grace"
            ? "text-green-400 font-semibold"
            : step.role === "blocker"
            ? "text-amber-400"
            : "text-slate-400";
          return (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="w-4 text-center text-slate-600">{i + 1}.</span>
              <span className="w-20 tabular-nums text-slate-300">
                {step.attacker_power.toLocaleString()}
                {step.don_attached > 0 && (
                  <span className="text-blue-400"> +{step.don_attached}⬡</span>
                )}
              </span>
              <span className="text-slate-500">→</span>
              <span className="w-16 tabular-nums text-slate-400">{step.target_power.toLocaleString()}</span>
              <span className={`flex-1 ${roleCls}`}>= {step.final_power.toLocaleString()} ({roleLabel})</span>
            </div>
          );
        })}
      </div>

      {/* Raison si non lethal */}
      {!isLethal && reason && (
        <div className="mt-1 text-xs text-amber-400">⚠️ {reason}</div>
      )}
    </div>
  );
}
