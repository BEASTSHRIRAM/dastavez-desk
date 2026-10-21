import type { Material } from "./paper";

export const SHEET_COUNT = 24;
export const SHEET = { w: 1.5, d: 1.05, t: 0.026 };

export interface Pose {
  p: [number, number, number];
  r: [number, number, number];
  s: number;
}

const flat = (x: number, y: number, z: number, ry = 0, s = 1): Pose => ({ p: [x, y, z], r: [0, ry, 0], s });
/** Upright: the sheet stands on its long edge, facing +z. */
const upright = (x: number, z: number, ry = 0, y = SHEET.d / 2): Pose => ({ p: [x, y, z], r: [Math.PI / 2, ry, 0], s: 1 });

const jitter = (i: number, amp: number) => (Math.sin(i * 12.9898) * 43758.5453 % 1) * amp;

/** Where each of the 24 sheets rests for a given workspace identity. Same sheets, different arrangement. */
export function layout(material: Material): Pose[] {
  const out: Pose[] = [];
  switch (material) {
    case "archival": {
      // three tidy stacks, like a filing shelf: structured, precise
      for (let i = 0; i < SHEET_COUNT; i++) {
        const stack = Math.floor(i / 8);
        out.push(flat((stack - 1) * 1.85, 0.02 + (i % 8) * (SHEET.t + 0.012), jitter(i, 0.03), jitter(i + 3, 0.05)));
      }
      return out;
    }
    case "architectural": {
      // a floor plan: tiles on the ground, upright sheets as walls
      const tiles: [number, number][] = [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1], [0, 2], [1, 2]];
      tiles.forEach(([cx, cz]) => out.push(flat((cx - 1.5) * 1.58, 0.02, (cz - 1) * 1.13)));
      const walls: [number, number, number][] = [
        [-2.4, -1.7, 0], [-0.8, -1.7, 0], [0.8, -1.7, 0], [2.4, -1.7, 0], [-3.2, -0.6, Math.PI / 2], [3.2, -0.6, Math.PI / 2],
        [-3.2, 0.6, Math.PI / 2], [3.2, 0.6, Math.PI / 2], [0.0, 0.0, Math.PI / 2], [-1.6, 1.4, 0], [0.0, 1.7, Math.PI / 2],
        [1.6, 1.0, 0], [-0.05, -0.7, Math.PI / 2], [2.0, 0.2, Math.PI / 2],
      ];
      walls.slice(0, SHEET_COUNT - tiles.length).forEach(([x, z, ry]) => out.push(upright(x, z, ry)));
      return out;
    }
    case "procedural": {
      // an ordered queue of upright records, one drawn out for processing
      for (let i = 0; i < SHEET_COUNT; i++) {
        const pulled = i === 9;
        out.push({ p: [(i - 11.5) * 0.4, pulled ? SHEET.d / 2 + 0.55 : SHEET.d / 2, pulled ? 0.9 : 0], r: [Math.PI / 2, Math.PI / 2 - (pulled ? 0.45 : 0.0), 0], s: 1 });
      }
      return out;
    }
    case "routes": {
      // sheets laid along a winding route, like an itinerary unrolling
      for (let i = 0; i < SHEET_COUNT; i++) {
        const t = i / (SHEET_COUNT - 1);
        const x = (t - 0.5) * 10;
        const z = Math.sin(t * Math.PI * 1.7) * 1.9;
        const dz = Math.cos(t * Math.PI * 1.7) * 1.9 * Math.PI * 1.7 * 0.1;
        out.push({ p: [x, 0.02 + (i % 3) * 0.03, z], r: [0, -Math.atan2(dz, 1), (i % 2 ? 1 : -1) * 0.02], s: 0.82 });
      }
      return out;
    }
    case "ledger": {
      // aligned columns of records, ranked like a ledger
      const heights = [2, 5, 3, 7, 4, 3];
      let i = 0;
      heights.forEach((h, c) => {
        for (let k = 0; k < h && i < SHEET_COUNT; k++, i++) out.push(flat((c - 2.5) * 1.75, 0.02 + k * (SHEET.t + 0.01), 0));
      });
      return out;
    }
    default: {
      // home: a rising spiral of sheets
      for (let i = 0; i < SHEET_COUNT; i++) {
        const a = i * 0.36;
        out.push({ p: [Math.cos(a) * 2.3, 0.1 + i * 0.13, Math.sin(a) * 1.6], r: [0, -a + Math.PI / 2, 0.03 * (i % 3 - 1)], s: 1 });
      }
      return out;
    }
  }
  return out;
}

/** Hidden sheets (when a layout uses fewer than 24) sit in the stack at the origin, scaled to nothing. */
export function padded(material: Material): Pose[] {
  const poses = layout(material);
  while (poses.length < SHEET_COUNT) poses.push({ p: [0, 0.02, 0], r: [0, 0, 0], s: 0 });
  return poses;
}

/** The tidy stack the sheets assemble into when facts are extracted. */
export function assembled(i: number): Pose {
  return { p: [0, 0.16 + i * 0.011, 0.02], r: [0, jitter(i, 0.02), 0], s: 0.78 };
}
