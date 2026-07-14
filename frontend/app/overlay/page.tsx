"use client";

import { useEffect, useState } from "react";
import { fetchState } from "@/lib/api";
import type { LiveState } from "@/lib/types";
import { DefensePanel } from "@/components/DefensePanel";
import { MulliganPanel } from "@/components/MulliganPanel";
import { OppSeenPanel } from "@/components/OppSeenPanel";
import { OppKnownHandPanel } from "@/components/OppKnownHandPanel";
import { LethalPanel } from "@/components/LethalPanel";
import { MenacesPanel } from "@/components/MenacesPanel";
import { DrawOddsPanel } from "@/components/DrawOddsPanel";

const CARD =
  "rounded-lg bg-slate-900/70 backdrop-blur px-2.5 py-1.5 text-slate-200 pointer-events-auto";

/** Zone d'ancrage du HUD, en % de la fenêtre du jeu (l'overlay la recouvre exactement).
 *  Par défaut : la bande du chat du sim, à gauche entre les deux mains (option A : on le
 *  recouvre — son contenu est redondant avec le tracker). Réglable sans rebuild via
 *  `/overlay?zone=x:6,y:30,w:20,h:50` ; `?debug=1` dessine le contour pour caler. */
type Zone = { x: number; y: number; w: number; h: number };
const DEFAULT_ZONE: Zone = { x: 6, y: 30, w: 20, h: 50 };

function parseZone(s: string | null): Zone {
  const z = { ...DEFAULT_ZONE };
  for (const part of (s ?? "").split(",")) {
    const [k, v] = part.split(":");
    const n = parseFloat(v);
    if (!Number.isNaN(n) && (k === "x" || k === "y" || k === "w" || k === "h")) z[k] = n;
  }
  return z;
}

/** L'unique rappel d'état : ce que le sim ne montre PAS (leader adverse inféré, decks
 *  restants). Tout le reste (board, mains, vie, DON) est déjà visible dans le jeu. */
function StatusLine({ data }: { data: LiveState }) {
  const meDeck = data.me?.deck_remaining;
  const oppDeck = data.opp?.deck_remaining;
  return (
    <div className={`${CARD} flex items-center gap-2 text-[11px]`}>
      {data.is_solo && (
        <span className="text-amber-400" title="Solo vs Self">●</span>
      )}
      {data.exact_state && <span title="état exact (mod)">⚡</span>}
      <span
        className="min-w-0 truncate text-slate-300"
        title={data.opp?.leader_inferred
          ? "Leader adverse déduit des cartes vues (pas encore observé directement)" : undefined}
      >
        ADV&nbsp;: {data.opp?.leader_name ?? "?"}
        {data.opp?.leader_inferred && <span className="text-slate-500"> ≈</span>}
      </span>
      {(meDeck != null || oppDeck != null) && (
        <span className="ml-auto whitespace-nowrap tabular-nums text-slate-400"
              title="Cartes restantes dans les decks (moi · adv)">
          🂠 {meDeck ?? "?"} · {oppDeck ?? "?"}
        </span>
      )}
    </div>
  );
}

export default function OverlayPage() {
  const [data, setData] = useState<LiveState | null>(null);
  const [zone, setZone] = useState<Zone>(DEFAULT_ZONE);
  const [debug, setDebug] = useState(false);

  // Config par querystring (window.location : la page est 100 % client, export statique).
  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    setZone(parseZone(qs.get("zone")));
    setDebug(qs.get("debug") === "1");
  }, []);

  // Polling : fetch immédiat puis toutes les 1000 ms.
  useEffect(() => {
    const tick = async () => {
      const d = await fetchState();
      if (d) setData(d);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Fond transparent au runtime (neutralise le body bg-slate-950 du layout racine).
  useEffect(() => {
    const prevH = document.documentElement.style.background;
    const prevB = document.body.style.background;
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    return () => {
      document.documentElement.style.background = prevH;
      document.body.style.background = prevB;
    };
  }, []);

  // Le gating serveur retire déjà les blocs non autorisés : la présence dans le payload
  // EST le contrat (ex. draw_odds fiables traversent même avec live_draw_odds OFF).
  const hasLethal =
    !!data?.lethal && (data.lethal.opp_can_lethal || data.lethal.me_can_lethal);
  const hasMenaces = !!data?.next_plays?.length;
  const hasDrawOdds = !!data?.draw_odds;

  return (
    <div
      className={`fixed pointer-events-none ${debug ? "outline-dashed outline-1 outline-amber-400" : ""}`}
      style={{
        left: `${zone.x}%`,
        top: `${zone.y}%`,
        width: `${zone.w}%`,
        // En debug on matérialise toute la zone, sinon on laisse le contenu dicter (borné).
        height: debug ? `${zone.h}%` : undefined,
        maxHeight: `${zone.h}%`,
      }}
    >
      <div className="flex max-h-full flex-col gap-1.5 overflow-hidden text-[11px]">
        {debug && (
          <div className="pointer-events-auto self-start rounded bg-amber-400 px-1 text-[10px] font-semibold text-slate-950">
            zone x:{zone.x} y:{zone.y} w:{zone.w} h:{zone.h}
          </div>
        )}

        {!data && <div className={CARD}>En attente du jeu…</div>}

        {data && (data.me || data.opp) && <StatusLine data={data} />}

        {/* Mulligan : décision du tour 0, visible seulement pendant la fenêtre de mulligan. */}
        {data?.in_mulligan && data.hand_score && (
          <div className={CARD}>
            <MulliganPanel hand={data.hand_score} />
          </div>
        )}

        {/* Défense : 100 % exact/public (mes counters/blockers/vie + board adverse visible). */}
        {data?.defense && (
          <div className={CARD}>
            <DefensePanel defense={data.defense} opp={data.opp} />
          </div>
        )}

        {/* Exemplaires adverses vus : comptage public exact, sous la défense. */}
        {data?.opp_seen && data.opp_seen.length > 0 && (
          <div className={CARD}>
            <OppSeenPanel list={data.opp_seen} />
          </div>
        )}

        {/* Connu en main adverse : révélations publiques (fair-play). */}
        {data?.opp_known_hand && data.opp_known_hand.length > 0 && (
          <div className={CARD}>
            <OppKnownHandPanel list={data.opp_known_hand} />
          </div>
        )}

        {data && hasLethal && (
          <div className={CARD}>
            <LethalPanel lethal={data.lethal} compact />
          </div>
        )}

        {data && hasMenaces && (
          <div className={CARD}>
            <MenacesPanel
              list={data.next_plays}
              donEst={data.opp_don_est}
              phase={data.next_plays_phase}
              turn={data.next_plays_turn}
              compact
            />
          </div>
        )}

        {data && hasDrawOdds && (
          <div className={CARD}>
            <DrawOddsPanel odds={data.draw_odds!} compact />
          </div>
        )}
      </div>
    </div>
  );
}
