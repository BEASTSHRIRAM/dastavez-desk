"use client";

import { useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { api, type AuditRow, type WorkflowEvent } from "@/lib/api";

gsap.registerPlugin(useGSAP);

const TONE: Record<string, string> = {
  validation_warning: "bg-ochre", record_ambiguous: "bg-ochre", missing_fields: "bg-ochre", workspace_suggestion: "bg-ochre",
  workflow_error: "bg-danger", export_failed: "bg-danger",
  approved: "bg-ok", export_ready: "bg-ok", workflow_complete: "bg-ok",
};

const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const ACTIONS: Record<string, string> = {
  case_created: "Case created", workflow_started: "Request received", facts_extracted: "Details read from your request",
  answers_recorded: "Answers recorded", preview_generated: "Draft rendered", approved: "Draft approved", exported: "File created",
  downloaded: "File downloaded", reopened: "Draft reopened", cancelled: "Case cancelled", attachment_added: "File attached",
  form_mapping_changed: "Form mapping changed", workflow_completed: "Case finished", workflow_failed: "Run stopped by an error", transcribed: "Speech transcribed",
};

export function ActivityPanel({ caseId, events }: { caseId: string; events: WorkflowEvent[] }) {
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [err, setErr] = useState("");
  const list = useRef<HTMLOListElement>(null);
  const seen = useRef(0);

  // New events slide in; earlier ones stay still.
  useGSAP(() => {
    const items = list.current?.querySelectorAll<HTMLElement>("[data-new]") ?? [];
    if (!items.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    gsap.from(items, { opacity: 0, x: 12, duration: 0.35, ease: "power2.out", stagger: 0.06 });
  }, { scope: list, dependencies: [events.length] });

  const recent = events.slice(-40);
  const prior = seen.current;
  seen.current = events.length;

  return (
    <section aria-label="Activity" className="space-y-3">
      <h2 className="font-display text-xl">What is happening</h2>
      {recent.length === 0 ? <p className="text-[0.9375rem] text-muted">Nothing yet. Progress appears here as soon as you start.</p> : (
        <ol ref={list} className="space-y-2.5" aria-live="polite">
          {recent.map((e, i) => (
            <li key={e.id} data-new={events.length - recent.length + i >= prior ? "" : undefined} className="flex gap-3 text-[0.9375rem]">
              <span aria-hidden className={`mt-[0.45rem] h-2 w-2 shrink-0 rounded-full ${TONE[e.type] ?? "bg-cobalt"}`} />
              <span className="min-w-0"><span className="block">{e.message}</span><span className="text-[0.75rem] text-muted">{time(e.created_at)}</span></span>
            </li>
          ))}
        </ol>
      )}
      <details className="border-t border-rule pt-3 text-[0.9375rem]" onToggle={(e) => {
        if ((e.target as HTMLDetailsElement).open) api.audit(caseId).then(setAudit).catch((x) => setErr(x.message));
      }}>
        <summary className="cursor-pointer underline decoration-rule underline-offset-4 hover:text-cobalt">Audit trail</summary>
        {err && <p className="mt-2 text-danger">{err}</p>}
        {audit && (
          <ul className="mt-2 space-y-1.5">
            {audit.length === 0 && <li className="text-muted">No audit entries yet.</li>}
            {audit.map((a) => <li key={a.id} className="flex justify-between gap-3"><span>{ACTIONS[a.action] ?? a.action.replace(/_/g, " ")}</span><span className="shrink-0 text-[0.8125rem] text-muted">{time(a.created_at)}</span></li>)}
          </ul>
        )}
      </details>
    </section>
  );
}

const STEPS = [
  { key: "intake", label: "Describe" },
  { key: "questions", label: "Answer" },
  { key: "review", label: "Review" },
  { key: "export", label: "Export" },
];
const AT: Record<string, number> = { intake: 0, processing: 0, failed: 0, awaiting_input: 1, review: 2, approved: 3, exported: 3, cancelled: 0 };

/** The job really is a sequence, so the stage markers are numbered. */
export function Steps({ status }: { status: string }) {
  const at = AT[status] ?? 0;
  return (
    <ol className="flex flex-wrap gap-x-6 gap-y-1 text-[0.9375rem]" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s.key} aria-current={i === at ? "step" : undefined} className={i === at ? "font-semibold text-ink" : i < at ? "text-ok" : "text-muted"}>
          <span className="tabular-nums">{i + 1}.</span> {s.label}{i < at && <span className="sr-only"> (done)</span>}
        </li>
      ))}
    </ol>
  );
}
