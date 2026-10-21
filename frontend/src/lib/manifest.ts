/**
 * Generative-UI manifest schema. This is the frontend's own validation of what the agent returned:
 * strict objects (unknown keys rejected) and a closed set of component names. There is no field
 * through which a manifest could carry HTML, script or a component we have not written.
 */
import { z } from "zod";

const provenance = z.strictObject({
  origin: z.string().nullable().optional(),
  quote: z.string().nullable().optional(),
  status: z.enum(["confirmed", "source", "suggested", "default", "none"]),
  confidence: z.number().nullable().optional(),
});

export const FIELD_KINDS = [
  "text_input", "long_text", "person", "address", "phone", "currency", "number", "date",
  "select", "multi_select", "yes_no", "party_select",
] as const;
export type FieldKind = (typeof FIELD_KINDS)[number];

const fieldComponent = z.strictObject({
  component: z.enum(FIELD_KINDS),
  field_id: z.string(),
  label: z.string(),
  required: z.boolean(),
  help: z.string().nullable().optional(),
  value: z.unknown().optional(),
  validation: z.strictObject({
    min: z.number().nullable().optional(),
    max: z.number().nullable().optional(),
    pattern: z.string().nullable().optional(),
    options: z.array(z.string()),
  }),
  provenance,
  high_impact: z.boolean(),
  needs_confirmation: z.boolean(),
  optional: z.boolean(),
  party_options: z.array(z.strictObject({ id: z.string(), label: z.string(), detail: z.string().nullable().optional() })),
});

const missingInfo = z.strictObject({
  component: z.literal("missing_info"),
  message: z.string(),
  field_ids: z.array(z.string()),
});

const conflictChoice = z.strictObject({
  component: z.literal("conflict_choice"),
  field_id: z.string(),
  label: z.string(),
  options: z.array(z.strictObject({ value: z.unknown(), origin: z.string().nullable().optional(), quote: z.string().nullable().optional() })),
});

const sourceEvidence = z.strictObject({
  component: z.literal("source_evidence"),
  items: z.array(z.record(z.string(), z.unknown())),
});

const fileAttachment = z.strictObject({
  component: z.literal("file_attachment"),
  label: z.string(),
  kind: z.enum(["form", "supporting"]),
  accept: z.array(z.string()),
  help: z.string().nullable().optional(),
  uploaded: z.array(z.record(z.string(), z.unknown())),
  mapping: z.record(z.string(), z.string()),
  mappable_fields: z.array(z.record(z.string(), z.string())),
});

const documentChecklist = z.strictObject({
  component: z.literal("document_checklist"),
  title: z.string(),
  items: z.array(z.string()),
  source: z.string().nullable().optional(),
  last_verified: z.string().nullable().optional(),
});

const changeComparison = z.strictObject({
  component: z.literal("change_comparison"),
  doc_key: z.string(),
  title: z.string(),
  sections: z.array(z.strictObject({ approved: z.string(), draft: z.string(), changed: z.boolean() })),
});

const block = z.looseObject({ type: z.enum(["header", "footer", "title", "heading", "paragraph", "bullet", "table"]) });

const documentPreview = z.strictObject({
  component: z.literal("document_preview"),
  doc_key: z.string(),
  title: z.string(),
  blocks: z.array(block),
  template: z.record(z.string(), z.unknown()).nullable().optional(),
  unavailable: z.string().nullable().optional(),
});

const issue = z.strictObject({
  key: z.string().nullable().optional(),
  field_id: z.string().nullable().optional(),
  code: z.string(),
  severity: z.enum(["error", "warning"]),
  message: z.string(),
});

const approvalPanel = z.strictObject({
  component: z.literal("approval_panel"),
  issues: z.array(issue),
  confirm_fields: z.array(z.strictObject({ field_id: z.string(), label: z.string(), value: z.unknown() })),
  can_approve: z.boolean(),
  approved: z.boolean(),
  acknowledgements: z.array(z.strictObject({ key: z.string(), message: z.string() })),
  disclaimers: z.array(z.string()),
});

const exportOptions = z.strictObject({
  component: z.literal("export_options"),
  documents: z.array(z.strictObject({ doc_key: z.string(), title: z.string(), formats: z.array(z.string()) })),
  pdf_available: z.boolean(),
  exported: z.array(z.record(z.string(), z.unknown())),
});

const clientMessage = z.strictObject({
  component: z.literal("client_message"),
  title: z.string(),
  text: z.string(),
});

const component = z.union([
  fieldComponent, missingInfo, conflictChoice, sourceEvidence, fileAttachment, documentChecklist,
  changeComparison, documentPreview, approvalPanel, exportOptions, clientMessage,
]);

export const manifestSchema = z.strictObject({
  version: z.literal(1),
  case_id: z.string(),
  stage: z.enum(["intake", "questions", "review", "export", "complete"]),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  sections: z.array(z.strictObject({
    title: z.string(),
    description: z.string().nullable().optional(),
    components: z.array(component),
  })),
});

export type Manifest = z.infer<typeof manifestSchema>;
export type Component = z.infer<typeof component>;
export type FieldComponent = z.infer<typeof fieldComponent>;
export type PreviewBlock = z.infer<typeof block> & { text?: string; rows?: string[][]; note?: boolean };
export type ApprovalPanel = z.infer<typeof approvalPanel>;
export type ExportOptions = z.infer<typeof exportOptions>;

export class ManifestRejected extends Error {}

/** Validate a manifest from the server. Anything outside the approved shape is refused outright. */
export function parseManifest(raw: unknown): Manifest {
  const result = manifestSchema.safeParse(raw);
  if (!result.success) {
    throw new ManifestRejected("The screen description from the server was not in an approved format, so it was not shown.");
  }
  return result.data;
}
