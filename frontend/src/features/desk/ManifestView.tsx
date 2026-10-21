"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import type { Attachment } from "@/lib/api";
import type { Component, FieldComponent, Manifest } from "@/lib/manifest";
import { Button, Notice } from "@/components/ui";
import { FieldInput, initialValue, validateField, type Raw } from "./FieldInput";
import { DocumentPaper } from "./DocumentPaper";
import { ChangeComparison } from "./ChangeComparison";

gsap.registerPlugin(useGSAP);

export interface Handlers {
  busy: string;
  canWrite: boolean;
  submitAnswers: (p: { answers: Record<string, unknown>; confirm: string[]; conflict_choices: Record<string, unknown> }) => Promise<void>;
  saveEdits: (answers: Record<string, unknown>) => Promise<void>;
  uploadForm: (f: File) => Promise<Attachment>;
  sampleForm: () => Promise<Attachment>;
  setMapping: (m: Record<string, string | null>) => Promise<void>;
}

const allComponents = (m: Manifest) => m.sections.flatMap((s) => s.components);
const fieldsIn = (cs: Component[]): FieldComponent[] => cs.filter((c): c is FieldComponent => "field_id" in c && "label" in c && "validation" in c);

/** Local form state for whatever fields the manifest asks for. Resets when the set of questions changes. */
function useManifestForm(fields: FieldComponent[]) {
  const sig = JSON.stringify(fields.map((f) => [f.field_id, f.value, f.needs_confirmation]));
  const [values, setValues] = useState<Record<string, Raw>>({});
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const [choices, setChoices] = useState<Record<string, unknown>>({});
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    setValues(Object.fromEntries(fields.map((f) => [f.field_id, initialValue(f)])));
    setConfirmed(new Set());
    setChoices({});
    setAttempted(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);
  const changed = (f: FieldComponent) => JSON.stringify(values[f.field_id] ?? "") !== JSON.stringify(initialValue(f));
  return { values, setValue: (id: string, v: Raw) => setValues((c) => ({ ...c, [id]: v })), confirmed, choices, attempted, setAttempted, changed,
    toggleConfirm: (id: string, on: boolean) => setConfirmed((c) => { const n = new Set(c); on ? n.add(id) : n.delete(id); return n; }),
    choose: (id: string, v: unknown) => setChoices((c) => ({ ...c, [id]: v })) };
}

const show = (v: unknown) => (typeof v === "boolean" ? (v ? "Yes" : "No") : v == null ? "" : String(v));

// ====================================================================== questions stage
export function QuestionsView({ manifest, serverErrors, handlers }: { manifest: Manifest; serverErrors: Record<string, string>; handlers: Handlers }) {
  const fields = fieldsIn(allComponents(manifest));
  const form = useManifestForm(fields);
  const root = useRef<HTMLDivElement>(null);

  // What was understood appears fact by fact, as the intake turns into structured fields.
  useGSAP(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.from("[data-reveal]", { opacity: 0, x: -10, duration: 0.45, ease: "power2.out", stagger: 0.07 });
    });
    return () => mm.revert();
  }, { scope: root, dependencies: [manifest.case_id, manifest.stage] });

  const asked = fields.filter((f) => !f.optional);
  const conflicts = allComponents(manifest).filter((c) => c.component === "conflict_choice");
  const errors: Record<string, string | null> = {};
  for (const f of fields) errors[f.field_id] = serverErrors[f.field_id] ?? (form.attempted ? validateField(f, form.values[f.field_id]) : null);

  const blockers = [
    ...asked.filter((f) => validateField(f, form.values[f.field_id])).map((f) => f.field_id),
    ...asked.filter((f) => f.needs_confirmation && !form.confirmed.has(f.field_id) && !form.changed(f)).map((f) => f.field_id),
    ...conflicts.filter((c) => c.component === "conflict_choice" && form.choices[c.field_id] === undefined).map((c) => (c as { field_id: string }).field_id),
  ];

  async function submit() {
    form.setAttempted(true);
    if (blockers.length) {
      document.getElementById(`field-${blockers[0]}`)?.focus();
      return;
    }
    const answers: Record<string, unknown> = {};
    const confirm: string[] = [];
    for (const f of fields) {
      const v = form.values[f.field_id];
      const empty = Array.isArray(v) ? v.length === 0 : (v ?? "").trim() === "";
      if (empty) continue;
      if (f.needs_confirmation && !form.changed(f)) { if (form.confirmed.has(f.field_id)) confirm.push(f.field_id); continue; }
      if (form.changed(f) || (f.required && !f.optional)) answers[f.field_id] = v;
    }
    await handlers.submitAnswers({ answers, confirm, conflict_choices: form.choices });
  }

  return (
    <div ref={root} className="space-y-8">
      {manifest.sections.map((s) => {
        const optionalOnly = s.components.length > 0 && s.components.every((c) => "optional" in c && c.optional);
        const body = (
          <div className="space-y-5">
            {s.components.map((c, i) => (
              <ComponentView key={i} c={c} form={form} errors={errors} handlers={handlers} />
            ))}
          </div>
        );
        return (
          <section key={s.title} aria-labelledby={`s-${s.title}`}>
            {optionalOnly ? (
              <details className="border-t border-rule pt-3">
                <summary className="cursor-pointer font-display text-xl" id={`s-${s.title}`}>{s.title} <span className="text-[0.9375rem] text-muted">(skip if not needed)</span></summary>
                <div className="mt-4">{body}</div>
              </details>
            ) : (
              <>
                <h2 id={`s-${s.title}`} className="font-display text-2xl">{s.title}</h2>
                {s.description && <p className="mb-4 text-muted">{s.description}</p>}
                {body}
              </>
            )}
          </section>
        );
      })}
      {(asked.length > 0 || conflicts.length > 0) && (
        <div className="flex flex-wrap items-center gap-4 border-t border-rule pt-5">
          <Button onClick={submit} busy={handlers.busy === "answers"} disabled={!handlers.canWrite}>Continue to review</Button>
          {form.attempted && blockers.length > 0 && <p role="alert" className="text-[0.9375rem] font-medium text-danger">Finish the {blockers.length} highlighted item{blockers.length !== 1 ? "s" : ""} to continue.</p>}
        </div>
      )}
      {asked.length === 0 && conflicts.length === 0 && (
        <div className="border-t border-rule pt-5"><Button onClick={submit} busy={handlers.busy === "answers"} disabled={!handlers.canWrite}>Continue to review</Button></div>
      )}
    </div>
  );
}

// ====================================================================== shared component renderer
type Form = ReturnType<typeof useManifestForm>;

function ComponentView({ c, form, errors, handlers, onEdit }: {
  c: Component; form: Form; errors: Record<string, string | null>; handlers: Handlers; onEdit?: (id: string) => void;
}) {
  switch (c.component) {
    case "missing_info":
      return <Notice kind="warning">{c.message}</Notice>;
    case "conflict_choice":
      return (
        <fieldset className="border border-ochre bg-ochre-soft p-4">
          <legend className="px-1 font-medium">{c.label}: two different values were found. Which is right?</legend>
          <div className="mt-2 space-y-2">
            {c.options.map((o, i) => (
              <label key={i} className="flex cursor-pointer items-start gap-3">
                <input type="radio" name={`choice-${c.field_id}`} className="mt-1 h-4 w-4 accent-cobalt" checked={form.choices[c.field_id] === o.value}
                  onChange={() => form.choose(c.field_id, o.value)} />
                <span><span className="font-medium">{show(o.value)}</span>
                  {o.quote && <span className="block text-[0.875rem] text-ink-2">From {o.origin?.startsWith("attachment") ? "an attached file" : "what you said"}: <q className="italic">{o.quote}</q></span>}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      );
    case "source_evidence":
      return (
        <dl className="divide-y divide-rule-soft border-y border-rule-soft">
          {c.items.map((it, i) => {
            const status = String(it.status);
            return (
              <div key={i} data-reveal className="grid gap-x-4 gap-y-0.5 py-2.5 sm:grid-cols-[11rem_1fr_auto]">
                <dt className="text-muted">{String(it.label)}</dt>
                <dd>
                  <span className="font-medium">{show(it.value)}</span>
                  {Boolean(it.quote) && <span className="block text-[0.875rem] text-ink-2">Heard: <q className="font-display italic">{String(it.quote)}</q></span>}
                </dd>
                <dd className="flex items-center gap-3 text-[0.8125rem]">
                  <span className={status === "confirmed" ? "text-ok" : "text-ochre"}>{status === "confirmed" ? "Confirmed" : status === "source" ? "From a saved record" : "Suggested"}</span>
                  {onEdit && <button type="button" className="underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => onEdit(String(it.field_id))}>Edit</button>}
                </dd>
              </div>
            );
          })}
        </dl>
      );
    case "file_attachment":
      return <FormAttachment c={c} handlers={handlers} />;
    case "document_checklist":
      return (
        <div className="border border-rule bg-sheet p-4">
          <h3 className="font-display text-xl">{c.title}</h3>
          <ul className="mt-2 space-y-1">{c.items.map((it) => <li key={it} className="flex gap-2"><span aria-hidden className="mt-1.5 h-3 w-3 shrink-0 border border-ink" />{it}</li>)}</ul>
          <p className="mt-3 text-[0.8125rem] text-muted">
            Source: {c.source ?? "none on file"}. Last verified: {c.last_verified ?? "not verified"}.
          </p>
        </div>
      );
    case "change_comparison":
      return <ChangeComparison title={c.title} sections={c.sections} />;
    case "document_preview":
      return c.unavailable ? <Notice kind="warning" title={c.title}>{c.unavailable}</Notice> : <DocumentPaper blocks={c.blocks as never} docKey={c.doc_key} />;
    case "approval_panel":
    case "export_options":
      return null; // rendered by the review and export stages, which own their actions
    default: {
      const f = c as FieldComponent;
      return (
        <FieldInput field={f} value={form.values[f.field_id] ?? ""} onChange={(v) => form.setValue(f.field_id, v)}
          error={errors[f.field_id]} confirmed={form.confirmed.has(f.field_id)} onConfirm={(on) => form.toggleConfirm(f.field_id, on)} disabled={!handlers.canWrite} />
      );
    }
  }
}

function FormAttachment({ c, handlers }: { c: Extract<Component, { component: "file_attachment" }>; handlers: Handlers }) {
  const form = c.uploaded.at(-1) as { name: string; fields: string[] } | undefined;
  const [map, setMap] = useState<Record<string, string>>(c.mapping);
  const [err, setErr] = useState("");
  useEffect(() => setMap(c.mapping), [c.mapping]);
  const wrap = async (fn: () => Promise<unknown>) => { setErr(""); try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : "That did not work."); } };

  return (
    <div className="space-y-3 border border-rule bg-sheet p-4">
      <p className="font-medium">{c.label}</p>
      {c.help && <p className="text-[0.875rem] text-muted">{c.help}</p>}
      <div className="flex flex-wrap items-center gap-4">
        <label className="cursor-pointer rounded-[3px] border border-ink px-4 py-2 font-medium hover:bg-ink hover:text-sheet has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-cobalt">
          Choose a file
          <input type="file" accept={c.accept.join(",")} className="sr-only" disabled={!handlers.canWrite}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) wrap(() => handlers.uploadForm(f)); e.target.value = ""; }} />
        </label>
        <button type="button" className="underline decoration-rule underline-offset-4 hover:text-cobalt" disabled={!handlers.canWrite} onClick={() => wrap(handlers.sampleForm)}>
          Use the sample demonstration form
        </button>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      {form && form.fields.length === 0 && <Notice kind="warning">No fields were found in {form.name}. Fillable PDFs and forms with labelled rows work best.</Notice>}
      {form && form.fields.length > 0 && (
        <div className="overflow-x-auto">
          <p className="mb-1 text-[0.875rem] text-muted">{form.name} is a form you supplied. It has not been checked as official or current.</p>
          <table className="w-full min-w-[420px] border-collapse text-left text-[0.9375rem]">
            <thead><tr className="border-b-2 border-ink"><th scope="col" className="py-1.5 pr-3 font-semibold">Form field</th><th scope="col" className="py-1.5 font-semibold">Answer to put there</th></tr></thead>
            <tbody>
              {form.fields.map((label, i) => (
                <tr key={label} className="border-b border-rule-soft">
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal"><label htmlFor={`map-${i}`}>{label}</label></th>
                  <td className="py-1.5">
                    <select id={`map-${i}`} value={map[label] ?? ""} disabled={!handlers.canWrite} className="w-full max-w-[18rem] border border-rule bg-sheet px-2 py-1 outline-none focus:border-cobalt"
                      onChange={(e) => { const next = { ...map }; if (e.target.value) next[label] = e.target.value; else delete next[label]; setMap(next); wrap(() => handlers.setMapping({ [label]: e.target.value || null })); }}>
                      <option value="">Leave empty</option>
                      {c.mappable_fields.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ====================================================================== review stage (center column)
export function ReviewCenter({ manifest, handlers, serverErrors }: { manifest: Manifest; handlers: Handlers; serverErrors: Record<string, string> }) {
  const comps = allComponents(manifest);
  const previews = comps.filter((c): c is Extract<Component, { component: "document_preview" }> => c.component === "document_preview");
  const comparisons = comps.filter((c): c is Extract<Component, { component: "change_comparison" }> => c.component === "change_comparison");
  const checklist = comps.filter((c) => c.component === "document_checklist");
  const evidence = comps.filter((c) => c.component === "source_evidence");
  const editSection = manifest.sections.find((s) => s.title === "Edit details");
  const editFields = fieldsIn(editSection?.components ?? []);
  const form = useManifestForm(editFields);
  const [tab, setTab] = useState(previews[0]?.doc_key ?? "");
  const active = previews.find((p) => p.doc_key === tab) ?? previews[0];
  const states = useMemo(() => {
    const out: Record<string, string> = {};
    for (const e of evidence) if (e.component === "source_evidence") for (const it of e.items) out[String(it.field_id)] = String(it.status);
    return out;
  }, [evidence]);

  const dirty = editFields.filter((f) => form.changed(f));
  const errors: Record<string, string | null> = {};
  for (const f of editFields) errors[f.field_id] = serverErrors[f.field_id] ?? validateField(f, form.values[f.field_id]);

  const jump = jumpToField;

  if (!active) return <Notice kind="warning">No preview is available yet.</Notice>;

  return (
    <div className="space-y-10">
      <div>
        {previews.length > 1 && (
          <div role="tablist" aria-label="Documents" className="mb-4 flex flex-wrap gap-1 border-b border-rule">
            {previews.map((p) => (
              <button key={p.doc_key} role="tab" id={`tab-${p.doc_key}`} aria-selected={p.doc_key === active.doc_key} aria-controls="doc-panel"
                tabIndex={p.doc_key === active.doc_key ? 0 : -1} onClick={() => setTab(p.doc_key)}
                onKeyDown={(e) => {
                  const i = previews.findIndex((x) => x.doc_key === active.doc_key);
                  const next = e.key === "ArrowRight" ? previews[(i + 1) % previews.length] : e.key === "ArrowLeft" ? previews[(i - 1 + previews.length) % previews.length] : null;
                  if (next) { e.preventDefault(); setTab(next.doc_key); document.getElementById(`tab-${next.doc_key}`)?.focus(); }
                }}
                className={`-mb-px border-b-2 px-4 py-2 text-[0.9375rem] transition-colors ${p.doc_key === active.doc_key ? "border-cobalt font-semibold text-ink" : "border-transparent text-muted hover:text-ink"}`}>
                {p.title}
              </button>
            ))}
          </div>
        )}
        <div id="doc-panel" role={previews.length > 1 ? "tabpanel" : undefined} aria-labelledby={previews.length > 1 ? `tab-${active.doc_key}` : undefined} className="space-y-3">
          {active.template && (
            <p className="text-[0.875rem] text-muted">
              Built from {String(active.template.title)}, version {String(active.template.version)}
              {active.template.is_demo ? ". This is a bundled demonstration template." : "."} Click any underlined value to edit it.
            </p>
          )}
          {active.unavailable
            ? <Notice kind="warning" title={active.title}>{active.unavailable}</Notice>
            : <DocumentPaper blocks={active.blocks as never} docKey={active.doc_key} onFieldClick={jump} states={states} />}
        </div>
      </div>

      {comparisons.filter((c) => c.component === "change_comparison" && c.doc_key === active.doc_key).map((c) => (
        <ComponentView key={c.doc_key} c={c} form={form} errors={errors} handlers={handlers} />
      ))}
      {checklist.map((c, i) => <ComponentView key={i} c={c} form={form} errors={errors} handlers={handlers} />)}
      {evidence.map((c, i) => (
        <section key={i} aria-labelledby="evidence-h">
          <h2 id="evidence-h" className="mb-2 font-display text-2xl">Where each value came from</h2>
          <ComponentView c={c} form={form} errors={errors} handlers={handlers} onEdit={jump} />
        </section>
      ))}

      {editFields.length > 0 && (
        <details id="edit-details" className="border border-rule bg-sheet p-4">
          <summary className="cursor-pointer font-display text-xl">Edit details</summary>
          <div className="mt-4 space-y-5">
            {editFields.map((f) => (
              <FieldInput key={f.field_id} field={{ ...f, needs_confirmation: false }} value={form.values[f.field_id] ?? ""} onChange={(v) => form.setValue(f.field_id, v)}
                error={errors[f.field_id]} disabled={!handlers.canWrite} />
            ))}
            <Button onClick={() => handlers.saveEdits(Object.fromEntries(dirty.map((f) => [f.field_id, form.values[f.field_id]])))}
              busy={handlers.busy === "edit"} disabled={!handlers.canWrite || dirty.length === 0 || dirty.some((f) => errors[f.field_id])}>
              Save {dirty.length || ""} change{dirty.length === 1 ? "" : "s"}
            </Button>
          </div>
        </details>
      )}
    </div>
  );
}

/** Opens the edit form and focuses a field. Used by the approval panel's "Go to field". */
export function jumpToField(fieldId: string) {
  const details = document.getElementById("edit-details") as HTMLDetailsElement | null;
  if (details) details.open = true;
  requestAnimationFrame(() => {
    const el = document.getElementById(`field-${fieldId}`);
    el?.scrollIntoView({ block: "center" });
    (el as HTMLElement | null)?.focus({ preventScroll: true });
  });
}
