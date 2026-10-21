"use client";

import { useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import type { ApprovalPanel as Approval, ExportOptions } from "@/lib/manifest";
import type { CaseOut } from "@/lib/api";
import { Button, Notice } from "@/components/ui";

gsap.registerPlugin(useGSAP);

const display = (v: unknown) => (typeof v === "boolean" ? (v ? "Yes" : "No") : String(v ?? ""));

export function ApprovalPanelView({ panel, busy, onApprove, onFix, canWrite }: {
  panel: Approval; busy: boolean; canWrite: boolean;
  onApprove: (confirm: string[], note: string) => void; onFix: (fieldId: string) => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const errors = panel.issues.filter((i) => i.severity === "error");
  const warnings = panel.issues.filter((i) => i.severity === "warning");
  const allChecked = panel.confirm_fields.every((f) => checked.has(f.field_id));
  const ready = panel.can_approve && allChecked && canWrite;

  if (panel.approved) {
    return <Notice kind="ok" title="Approved">The reviewed values are locked in. Export the documents below, or reopen the draft to change something (it will need approving again).</Notice>;
  }

  const issueList = (items: typeof panel.issues, kind: "error" | "warning") => items.length > 0 && (
    <div>
      <h3 className={`font-semibold ${kind === "error" ? "text-danger" : "text-ochre"}`}>
        {kind === "error" ? `Fix before approving (${items.length})` : `Worth a look (${items.length})`}
      </h3>
      <ul className="mt-1 space-y-1">
        {items.map((i, k) => (
          <li key={k} className="flex flex-wrap items-baseline gap-x-3">
            <span>{i.message}</span>
            {i.field_id && <button type="button" className="text-[0.875rem] underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => onFix(i.field_id!)}>Go to field</button>}
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <section aria-label="Approval" className="space-y-5 border border-ink bg-sheet p-5">
      <h2 className="font-display text-2xl">Approve this draft</h2>
      {issueList(errors, "error")}
      {issueList(warnings, "warning")}
      {panel.confirm_fields.length > 0 && (
        <fieldset>
          <legend className="font-semibold">Confirm the values that matter</legend>
          <p className="text-[0.875rem] text-muted">Names, amounts, dates and records are checked one by one. Tick each once it is right.</p>
          <ul className="mt-2 divide-y divide-rule-soft border-y border-rule-soft">
            {panel.confirm_fields.map((f) => (
              <li key={f.field_id}>
                <label className="flex cursor-pointer items-center gap-3 py-2">
                  <input type="checkbox" className="h-4 w-4 accent-cobalt" checked={checked.has(f.field_id)}
                    onChange={(e) => setChecked((cur) => { const n = new Set(cur); e.target.checked ? n.add(f.field_id) : n.delete(f.field_id); return n; })} />
                  <span className="min-w-0 flex-1"><span className="text-muted">{f.label}: </span><span className="font-medium">{display(f.value)}</span></span>
                </label>
              </li>
            ))}
          </ul>
          <button type="button" className="mt-2 text-[0.875rem] underline decoration-rule underline-offset-4 hover:text-cobalt"
            onClick={() => setChecked(new Set(panel.confirm_fields.map((f) => f.field_id)))}>
            Tick all after checking each one
          </button>
        </fieldset>
      )}
      <div>
        <label htmlFor="approval-note" className="font-medium">Note for the record <span className="font-normal text-muted">(optional)</span></label>
        <input id="approval-note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full border border-rule bg-sheet px-3 py-2 outline-none focus:border-cobalt" />
      </div>
      <ul className="space-y-1 text-[0.875rem] text-muted">{panel.disclaimers.map((d) => <li key={d}>{d}</li>)}</ul>
      <div className="flex flex-wrap items-center gap-4">
        <Button onClick={() => onApprove([...checked], note)} disabled={!ready} busy={busy}>Approve draft</Button>
        {!ready && <p className="text-[0.875rem] text-muted" aria-live="polite">
          {!canWrite ? "Your role can't approve drafts."
            : !panel.can_approve ? "Resolve the items above first."
            : "Tick every value above to approve."}
        </p>}
      </div>
    </section>
  );
}

const FORMAT_LABEL: Record<string, string> = { docx: "Word (.docx)", pdf: "PDF", xlsx: "Excel (.xlsx)", csv: "CSV" };

export function ExportView({ options, caseData, busy, onExport, onDownload, onFinish, onReopen, canWrite }: {
  options: ExportOptions; caseData: CaseOut; busy: string; canWrite: boolean;
  onExport: (formats: Record<string, string[]>) => void; onDownload: (id: string, name: string) => void;
  onFinish: () => void; onReopen: () => void;
}) {
  const [pick, setPick] = useState<Record<string, Set<string>>>(() => Object.fromEntries(options.documents.map((d) => [d.doc_key, new Set([d.formats[0]])])));
  const done = caseData.status === "exported";
  const total = Object.values(pick).reduce((n, s) => n + s.size, 0);
  const mark = useRef<SVGPathElement>(null);
  const root = useRef<HTMLDivElement>(null);

  // Completion mark draws itself once files exist.
  useGSAP(() => {
    if (!done || !mark.current) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const len = mark.current!.getTotalLength();
      gsap.fromTo(mark.current, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.7, ease: "power2.out" });
    });
    return () => mm.revert();
  }, { scope: root, dependencies: [done, caseData.documents.length] });

  return (
    <div ref={root} className="space-y-6">
      {done && (
        <div className="flex items-center gap-4 border border-ok bg-ok-soft p-4">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden>
            <circle cx="20" cy="20" r="18" stroke="#2b6648" strokeWidth="2" />
            <path ref={mark} d="M11 21l6 6 12-14" stroke="#2b6648" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <p className="font-display text-xl">{caseData.documents.length} file{caseData.documents.length !== 1 ? "s" : ""} ready to download</p>
            <p className="text-[0.9375rem] text-ink-2">Files from sample templates are marked as samples in their name.</p>
          </div>
        </div>
      )}

      {canWrite && (
        <fieldset className="space-y-4">
          <legend className="font-display text-xl">Choose formats</legend>
          {options.documents.map((d) => (
            <div key={d.doc_key} className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft pb-3">
              <p className="font-medium">{d.title}</p>
              <div className="flex flex-wrap gap-x-5 gap-y-1">
                {d.formats.map((f) => {
                  const blocked = f === "pdf" && !options.pdf_available;
                  return (
                    <label key={f} className={`flex items-center gap-2 ${blocked ? "text-muted" : "cursor-pointer"}`}>
                      <input type="checkbox" className="h-4 w-4 accent-cobalt" disabled={blocked} checked={pick[d.doc_key]?.has(f) ?? false}
                        onChange={(e) => setPick((cur) => { const s = new Set(cur[d.doc_key]); e.target.checked ? s.add(f) : s.delete(f); return { ...cur, [d.doc_key]: s }; })} />
                      {FORMAT_LABEL[f] ?? f}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          {!options.pdf_available && options.documents.some((d) => d.formats.includes("pdf")) && (
            <Notice kind="warning" title="PDF export is not available on this server">
              PDF needs LibreOffice installed on the server (or SOFFICE_PATH set). Word files work now, and you can convert them yourself.
            </Notice>
          )}
          <Button onClick={() => onExport(Object.fromEntries(Object.entries(pick).map(([k, s]) => [k, [...s]])))} busy={busy === "export"} disabled={total === 0}>
            Create {total} file{total !== 1 ? "s" : ""}
          </Button>
        </fieldset>
      )}

      {caseData.export_failures.length > 0 && (
        <Notice kind="error" title="Some files could not be created">
          <ul className="list-disc pl-5">{caseData.export_failures.map((f) => <li key={f}>{f}</li>)}</ul>
        </Notice>
      )}

      {caseData.documents.length > 0 && (
        <section aria-label="Generated files">
          <h3 className="font-display text-xl">Files</h3>
          <ul className="mt-2 divide-y divide-rule-soft border-y border-rule-soft">
            {caseData.documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <span><span className="font-medium">{d.title}</span> <span className="text-muted">{FORMAT_LABEL[d.fmt] ?? d.fmt}</span></span>
                <Button variant="secondary" onClick={() => onDownload(d.id, `${d.title}.${d.fmt}`)}>Download</Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {canWrite && (
        <div className="flex flex-wrap gap-4 border-t border-rule pt-4">
          <Button variant="quiet" onClick={onReopen} busy={busy === "reopen"}>Reopen to change something</Button>
          {done && <Button variant="secondary" onClick={onFinish} busy={busy === "finish"}>Finish this case</Button>}
        </div>
      )}
    </div>
  );
}
