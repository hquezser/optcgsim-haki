"use client";

export function LifeDisplay({ life }: { life: number | null }) {
  if (life == null)
    return <b className="text-slate-500">?</b>;
  const crit = life <= 2;
  const n = Math.max(0, Math.min(5, life));
  const col = crit ? "text-red-400" : "text-green-400";
  return (
    <span className="inline-flex items-center gap-1">
      <b className={crit ? "text-red-400" : "text-green-400"}>{life}</b>
      <span className={crit ? "animate-pulse" : ""}>
        <span className={col}>{"●".repeat(n)}</span>
        <span className="text-slate-600">{"○".repeat(Math.max(0, 5 - n))}</span>
      </span>
    </span>
  );
}
