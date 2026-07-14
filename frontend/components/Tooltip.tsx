"use client";

import { useState, ReactNode } from "react";

/**
 * Tooltip — équivalent React du _tip() de liveserver.py.
 *
 * Affiche un label cliquable/survivable qui révèle une explication
 * détaillée pour aider à comprendre les termes statistiques.
 */
export function Tooltip({
  label,
  text,
  className = "",
}: {
  label: ReactNode;
  text: string;
  className?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <span
      className={`relative inline-block ${className}`}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onClick={() => setShow(!show)}
    >
      <span className="cursor-help border-b border-dotted border-slate-500 text-slate-400">
        {label}
      </span>
      {show && (
        <span className="absolute bottom-full left-0 z-50 mb-1 w-64 rounded-lg border border-slate-600 bg-slate-900 p-2 text-xs font-normal leading-relaxed text-slate-300 shadow-xl">
          {text}
        </span>
      )}
    </span>
  );
}

/**
 * TooltipIcon — un "?" dans un cercle qui affiche un tooltip au survol.
 * Utilisé pour les titres de sections.
 */
export function TooltipIcon({ text }: { text: string }) {
  return (
    <Tooltip
      label={
        <span className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-600 text-[10px] text-slate-500">
          ?
        </span>
      }
      text={text}
    />
  );
}
