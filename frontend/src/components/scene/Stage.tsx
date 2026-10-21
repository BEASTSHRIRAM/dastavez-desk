"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { Material } from "./paper";
import { canUseWebGL } from "./paper";
import type { SceneMode } from "./Installation";

const Installation = dynamic(() => import("./Installation"), { ssr: false, loading: () => <StaticStack material="home" /> });

const KEY = "dastavez.reduce3d";

/** One switch for every 3D surface: reduced motion, a stored preference, or no WebGL means a static drawing. */
export function useReduce3D(): { reduced: boolean; setReduced: (v: boolean) => void; ready: boolean } {
  const [reduced, setReducedState] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let stored = false;
    try { stored = window.localStorage.getItem(KEY) === "1"; } catch { /* storage blocked */ }
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedState(stored || media.matches || !canUseWebGL());
    update();
    setReady(true);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return {
    reduced,
    ready,
    setReduced: (v) => {
      try { window.localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* ignore */ }
      setReducedState(v || !canUseWebGL());
    },
  };
}

export function Stage({ material, mode = "idle", shift = 0, className = "", label }: {
  material: Material; mode?: SceneMode; shift?: number; className?: string; label?: string;
}) {
  const { reduced, ready } = useReduce3D();
  if (!ready) return <div className={className} aria-hidden />;
  if (reduced) return <StaticStack material={material} className={className} label={label} />;
  return <Installation material={material} mode={mode} shift={shift} className={className} label={label} />;
}

/** Static fallback: the same sheets, drawn flat. No WebGL, no motion. */
export function StaticStack({ material, className = "", label }: { material: Material; className?: string; label?: string }) {
  const sheets = Array.from({ length: 7 }, (_, i) => i);
  const spread = material === "routes" ? 34 : material === "ledger" ? 26 : material === "architectural" ? 20 : 14;
  return (
    <div className={`flex items-center justify-center ${className}`} role="img" aria-label={label ?? "Stacked document sheets"}>
      <svg viewBox="0 0 320 240" className="h-full max-h-[420px] w-full max-w-[520px]" aria-hidden>
        {sheets.map((i) => (
          <g key={i} transform={`translate(${60 + i * spread * 0.55} ${150 - i * 14}) skewX(-28) scale(1 0.62)`}>
            <rect width="140" height="100" fill="#fbfaf6" stroke="#b8b3a5" />
            <rect x="12" y="12" width="46" height="4" fill="#14171f" />
            {[0, 1, 2, 3, 4].map((l) => <rect key={l} x="12" y={30 + l * 11} width={110 - (l === 4 ? 50 : 0)} height="1.5" fill="#14171f" opacity=".3" />)}
            {i === 6 && <rect x="104" y="78" width="16" height="12" fill="#1f43d6" />}
          </g>
        ))}
      </svg>
    </div>
  );
}
