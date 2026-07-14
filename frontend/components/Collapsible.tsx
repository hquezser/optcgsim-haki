"use client";

import { useState, ReactNode } from "react";

/**
 * Collapsible — panneau repliable pour réduire la surcharge visuelle.
 *
 * En mode "coach" (defaultOpen=false), le panneau est fermé par défaut.
 * En mode "full" (defaultOpen=true), il est ouvert.
 * L'utilisateur peut toujours cliquer pour voir les détails.
 */
export function Collapsible({
  title,
  badge,
  defaultOpen = false,
  forceOpen = false,
  children,
}: {
  title: ReactNode;
  badge?: ReactNode;
  defaultOpen?: boolean;
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = forceOpen || open;

  return (
    <section className="rounded-lg border border-slate-700 p-3">
      <button
        onClick={() => !forceOpen && setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
        disabled={forceOpen}
      >
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <span className={`text-xs transition-transform ${isOpen ? "rotate-90" : ""}`}>▶</span>
          {title}
          {badge}
        </h2>
      </button>
      {isOpen && <div className="mt-2">{children}</div>}
    </section>
  );
}
