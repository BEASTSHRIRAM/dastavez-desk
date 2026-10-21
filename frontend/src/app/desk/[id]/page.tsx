"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { api, ApiError, type Capabilities, type WorkspaceInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { Button, ConfirmDialog, Notice, Spinner, StatusPill, useToast } from "@/components/ui";
import { Stage } from "@/components/scene/Stage";
import type { SceneMode } from "@/components/scene/Installation";
import { MATERIAL_FOR } from "@/lib/workspaces";
import { useCase } from "@/features/desk/useCase";
import { VoiceIntake } from "@/features/desk/VoiceIntake";
import { QuestionsView, ReviewCenter, jumpToField, type Handlers } from "@/features/desk/ManifestView";
import { ApprovalPanelView, ExportView } from "@/features/desk/ApprovalExport";
import { ActivityPanel, Steps } from "@/features/desk/ActivityPanel";

gsap.registerPlugin(useGSAP);

export default function DeskPage() {
  return <Shell wide><Desk /></Shell>;
}

function Desk() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const toast = useToast();
  const [view, setView] = useState<string | undefined>();
  const cs = useCase(id, view);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo>();
  const [busy, setBusy] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmCancel, setConfirmCancel] = useState(false);
  const stageBox = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const canWrite = session?.user.role !== "viewer";

  useEffect(() => { api.capabilities().then(setCaps).catch(() => {}); }, []);
  useEffect(() => { if (cs.data) api.workspaces().then((w) => setWorkspace(w.find((x) => x.id === cs.data!.workspace))).catch(() => {}); }, [cs.data?.workspace]); // eslint-disable-line react-hooks/exhaustive-deps

  const status = cs.data?.status ?? "intake";
  const reviewing = status === "review" || (view === "review" && (status === "approved" || status === "exported"));
  const exporting = !reviewing && (status === "approved" || status === "exported");
  const mode: SceneMode = status === "approved" || status === "exported" ? "done" : status === "awaiting_input" || status === "review" ? "assembling" : "idle";
  const slim = reviewing || exporting;

  // The 3D stage gives way to the document once there is something to review.
  useGSAP(() => {
    if (!stageBox.current) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => { gsap.to(stageBox.current, { height: slim ? 84 : 230, duration: 0.7, ease: "power3.inOut" }); });
    mm.add("(prefers-reduced-motion: reduce)", () => { gsap.set(stageBox.current, { height: slim ? 84 : 230 }); });
    return () => mm.revert();
  }, { dependencies: [slim] });

  // Between stages, the content settles in.
  useGSAP(() => {
    if (!content.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    gsap.fromTo(content.current, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.45, ease: "power2.out" });
  }, { dependencies: [cs.manifest?.stage ?? status, reviewing] });

  async function run(name: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(name);
    setErrors({});
    try {
      await fn();
      if (ok) toast(ok, "ok");
    } catch (e) {
      if (e instanceof ApiError) {
        setErrors(e.errors);
        toast(e.message, "error");
      } else toast(e instanceof Error ? e.message : "Something went wrong.", "error");
    } finally { setBusy(""); }
  }

  const handlers: Handlers = {
    busy, canWrite: !!canWrite,
    submitAnswers: (p) => run("answers", async () => cs.apply(await api.answers(id, p))),
    saveEdits: (answers) => run("edit", async () => cs.apply(await api.editInReview(id, answers)), "Draft updated."),
    uploadForm: async (f) => { const a = await api.upload(id, f, "form"); await cs.refresh(); return a; },
    sampleForm: async () => { const a = await api.sampleForm(id); await cs.refresh(); return a; },
    setMapping: async (m) => { await api.setMapping(id, m); await cs.refresh(); },
  };

  if (cs.loading && !cs.data) return <p className="flex items-center gap-2 text-muted"><Spinner /> Opening the case…</p>;
  if (!cs.data) return <Notice kind="error" title="This case could not be opened">{cs.error || "It may not exist, or it belongs to another business."} <Link href="/cases" className="underline">Back to cases</Link></Notice>;
  const c = cs.data;
  const m = cs.manifest;
  const approval = m?.sections.flatMap((s) => s.components).find((x) => x.component === "approval_panel");
  const exportOpts = m?.sections.flatMap((s) => s.components).find((x) => x.component === "export_options");
  const terminal = status === "cancelled" || status === "exported";

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="font-display text-3xl leading-tight sm:text-4xl">{workspace?.name ?? c.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-3"><StatusPill status={status} /><Steps status={status} /></div>
        </div>
        {canWrite && !terminal && <Button variant="quiet" onClick={() => setConfirmCancel(true)}>Cancel this case</Button>}
      </header>

      <div ref={stageBox} className="relative mb-6 overflow-hidden border-y border-rule bg-paper" style={{ height: 230 }}>
        <Stage material={MATERIAL_FOR[c.workspace] ?? "home"} mode={mode} intro={false} shift={0.28} className="absolute inset-0"
          label={mode === "idle" ? "Sheets waiting for your request" : "Sheets gathered into a folder as details are understood"} />
      </div>

      {!canWrite && <div className="mb-4"><Notice kind="info">Your role is viewer. You can read this case but not change it.</Notice></div>}
      {cs.error && <div className="mb-4"><Notice kind="error">{cs.error}</Notice></div>}

      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div ref={content} className="min-w-0">
          {status === "intake" && (
            <>
              <h2 className="mb-1 font-display text-2xl">Describe the job</h2>
              <p className="mb-5 max-w-[60ch] text-muted">Say it the way you would to a colleague. Names, amounts and dates are checked in the next step.</p>
              <VoiceIntake caseId={id} workspace={workspace} caps={caps} canWrite={!!canWrite} initial={c.transcript ?? ""}
                onStart={async (t) => { await api.startIntake(id, t); await cs.refresh(); }} />
            </>
          )}

          {status === "processing" && (
            <div className="space-y-3" role="status">
              <h2 className="flex items-center gap-3 font-display text-2xl"><Spinner className="h-5 w-5 text-cobalt" /> Reading your request</h2>
              <p className="max-w-[60ch] text-muted">Finding the details, matching saved records, choosing the approved template. This usually takes a few seconds.</p>
              {c.transcript && <blockquote className="max-w-[64ch] border-l-2 border-rule pl-4 font-display text-[1.0625rem] italic text-ink-2">{c.transcript}</blockquote>}
            </div>
          )}

          {status === "failed" && (
            <div className="space-y-3">
              <Notice kind="error" title="This run stopped before it finished">Your answers are saved. Retrying continues from where it stopped.</Notice>
              {canWrite && <Button onClick={() => run("retry", async () => { await api.retry(id); await cs.refresh(); })} busy={busy === "retry"}>Retry</Button>}
            </div>
          )}

          {status === "cancelled" && <Notice kind="info" title="This case was cancelled">Nothing was exported. <Link href="/workspaces" className="underline">Start a new job</Link></Notice>}

          {status === "awaiting_input" && m && <QuestionsView manifest={m} serverErrors={{ ...c.answer_errors, ...errors }} handlers={handlers} />}

          {reviewing && m && (
            <>
              <h2 className="mb-1 font-display text-2xl">Review the draft</h2>
              <p className="mb-5 max-w-[60ch] text-muted">Everything underlined came from your request or a saved record. Click a value to correct it.</p>
              <ReviewCenter manifest={m} handlers={handlers} serverErrors={{ ...c.answer_errors, ...errors }} />
            </>
          )}

          {exporting && exportOpts?.component === "export_options" && (
            <>
              <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="font-display text-2xl">{status === "exported" ? "Your files" : "Approved. Choose what to export"}</h2>
                <button className="text-[0.9375rem] underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => { setView("review"); }}>Look at the approved draft again</button>
              </div>
              <ExportView options={exportOpts} caseData={c} busy={busy} canWrite={!!canWrite}
                onExport={(f) => run("export", async () => cs.apply(await api.exportDocs(id, f)))}
                onDownload={(docId, name) => run("download", () => api.download(docId, name))}
                onFinish={() => run("finish", async () => cs.apply(await api.finish(id)), "Case finished.")}
                onReopen={() => run("reopen", async () => { setView(undefined); cs.apply(await api.reopen(id)); })} />
            </>
          )}
          {view === "review" && (status === "approved" || status === "exported") && (
            <div className="mt-6"><Button variant="quiet" onClick={() => setView(undefined)}>Back to export</Button></div>
          )}
        </div>

        <aside className="min-w-0 space-y-8 xl:sticky xl:top-6 xl:self-start" aria-label="Validation and activity">
          {reviewing && approval?.component === "approval_panel" && (
            <ApprovalPanelView panel={approval} busy={busy === "approve"} canWrite={!!canWrite}
              onFix={jumpToField} onApprove={(confirm, note, acknowledge) => run("approve", async () => { setView(undefined); cs.apply(await api.approve(id, confirm, note || undefined, acknowledge)); }, "Draft approved.")} />
          )}
          {status === "awaiting_input" && c.pending?.fields && (
            <Notice kind="warning" title="Why I stopped">I paused because {c.pending.fields.length} required or uncertain detail{c.pending.fields.length !== 1 ? "s were" : " was"} not clear from your request.</Notice>
          )}
          <ActivityPanel caseId={id} events={cs.events} />
          {workspace && <ul className="space-y-1.5 border-t border-rule pt-4 text-[0.8125rem] text-muted">{workspace.disclaimers.map((d) => <li key={d}>{d}</li>)}</ul>}
        </aside>
      </div>

      <ConfirmDialog open={confirmCancel} title="Cancel this case?" confirmLabel="Cancel the case" danger
        body="Nothing will be exported. Answers entered so far stay in the case history."
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => { setConfirmCancel(false); run("cancel", async () => cs.apply(await api.cancel(id)), "Case cancelled."); }} />
    </div>
  );
}
