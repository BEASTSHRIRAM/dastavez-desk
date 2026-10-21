import * as THREE from "three";

export type Material = "home" | "archival" | "architectural" | "procedural" | "routes" | "ledger";

const INK = "#14171f";
const COBALT = "#1f43d6";
const RULE = "#b8b3a5";

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Procedural sheet print. One drawing language, five patterns: what is printed on the paper tells the workspace. */
function draw(ctx: CanvasRenderingContext2D, w: number, h: number, material: Material, seed: number) {
  const r = rng(seed);
  ctx.fillStyle = "#fbfaf6";
  ctx.fillRect(0, 0, w, h);
  // paper fibre
  for (let i = 0; i < 260; i++) {
    ctx.fillStyle = `rgba(60,55,40,${0.02 + r() * 0.03})`;
    ctx.fillRect(r() * w, r() * h, 1 + r() * 2, 1);
  }
  ctx.lineWidth = 1;
  const line = (x1: number, y1: number, x2: number, y2: number, c = RULE, a = 1) => {
    ctx.strokeStyle = c;
    ctx.globalAlpha = a;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  };
  const textLines = (x: number, y: number, width: number, n: number, gap: number) => {
    for (let i = 0; i < n; i++) line(x, y + i * gap, x + width * (i === n - 1 ? 0.5 : 0.8 + r() * 0.2), y + i * gap, INK, 0.28);
  };
  const margin = w * 0.09;
  // heading block common to all
  ctx.fillStyle = INK;
  ctx.globalAlpha = 0.85;
  ctx.fillRect(margin, h * 0.1, w * 0.34, 5);
  ctx.globalAlpha = 1;

  if (material === "archival" || material === "home") {
    textLines(margin, h * 0.24, w - margin * 2, 11, 9);
    line(margin, h * 0.88, w * 0.45, h * 0.88, INK, 0.5);
    line(w * 0.2, 0, w * 0.2, h, COBALT, 0.35);
  } else if (material === "architectural") {
    for (let x = margin; x < w - margin; x += 18) line(x, h * 0.2, x, h * 0.9, RULE, 0.5);
    for (let y = h * 0.2; y < h * 0.9; y += 18) line(margin, y, w - margin, y, RULE, 0.5);
    ctx.strokeStyle = INK;
    ctx.lineWidth = 2;
    ctx.strokeRect(w * 0.22, h * 0.32, w * 0.5, h * 0.42);
    line(w * 0.22, h * 0.52, w * 0.5, h * 0.52, INK, 0.9);
    line(w * 0.5, h * 0.52, w * 0.5, h * 0.74, INK, 0.9);
  } else if (material === "procedural") {
    for (let i = 0; i < 5; i++) {
      const y = h * 0.22 + i * 26;
      ctx.strokeStyle = INK;
      ctx.globalAlpha = 0.45;
      ctx.strokeRect(margin, y, w - margin * 2, 18);
      ctx.globalAlpha = 1;
      line(margin + (w - margin * 2) * 0.32, y, margin + (w - margin * 2) * 0.32, y + 18, INK, 0.45);
    }
    ctx.fillStyle = COBALT;
    ctx.globalAlpha = 0.8;
    ctx.fillRect(w - margin - 18, h * 0.84, 18, 18);
    ctx.globalAlpha = 1;
  } else if (material === "routes") {
    ctx.setLineDash([4, 5]);
    ctx.strokeStyle = COBALT;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(margin, h * 0.78);
    ctx.bezierCurveTo(w * 0.3, h * 0.2, w * 0.55, h * 0.95, w - margin, h * 0.3);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = COBALT;
    for (const [x, y] of [[margin, h * 0.78], [w - margin, h * 0.3]]) {
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.strokeStyle = INK;
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    ctx.arc(w * 0.72, h * 0.72, 22, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
    textLines(margin, h * 0.24, w * 0.4, 4, 9);
  } else if (material === "ledger") {
    const cols = [0.42, 0.62, 0.8];
    for (const c of cols) line(w * c, h * 0.2, w * c, h * 0.92, RULE, 0.9);
    for (let y = h * 0.24; y < h * 0.92; y += 14) line(margin, y, w - margin, y, RULE, 0.55);
    for (let i = 0; i < 9; i++) line(w * (0.45 + (i % 3) * 0.18), h * 0.24 + i * 14 + 8, w * (0.58 + (i % 3) * 0.18), h * 0.24 + i * 14 + 8, INK, 0.45);
    line(margin, h * 0.2, w - margin, h * 0.2, INK, 0.9);
  }
}

const cache = new Map<string, THREE.CanvasTexture>();

export function paperTexture(material: Material, variant = 0): THREE.CanvasTexture {
  const key = `${material}:${variant}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = 226;
  draw(canvas.getContext("2d")!, canvas.width, canvas.height, material, variant * 7919 + material.length);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  cache.set(key, tex);
  return tex;
}

export function canUseWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}
