import type { Material } from "@/components/scene/paper";

/** Static copy for the public pages. The authenticated app reads the live definitions from the API. */
export const WORKSPACE_BRIEFS: { id: string; name: string; line: string; material: Material }[] = [
  { id: "legal", name: "Legal documents", line: "Affidavit and declaration drafts from your approved templates.", material: "archival" },
  { id: "property", name: "Property and rental", line: "Rental agreements and handover checklists from one set of facts.", material: "architectural" },
  { id: "government", name: "Applications centre", line: "Capture answers, map them to a form, list the missing papers.", material: "procedural" },
  { id: "travel", name: "Travel and visa", line: "One intake, then itinerary, checklist and cover-letter drafts.", material: "routes" },
  { id: "accounting", name: "Bookkeeping", line: "Dictate an expense, get a typed record and a spreadsheet.", material: "ledger" },
];

export const MATERIAL_FOR: Record<string, Material> = Object.fromEntries(WORKSPACE_BRIEFS.map((w) => [w.id, w.material]));
