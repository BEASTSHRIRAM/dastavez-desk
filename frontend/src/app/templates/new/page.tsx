"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError, type StudioAnalysis, type StudioBuilt, type StudioCandidate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { Button, Notice, useToast } from "@/components/ui";
import { DocumentPaper } from "@/features/desk/DocumentPaper";

type Row = StudioCandidate & { id: number };
const TYPES = [
  ["person", "Person's name"], ["text", "Short text"], ["longtext", "Long text"], ["address", "Address"], ["phone", "Phone number"],
  ["currency", "Amount (INR)"], ["number", "Number"], ["date", "Date"],
] as const;
const FIELD_RX = /^[a-z][a-z0-9_]{1,40}$/;

export default function NewTemplate() {
  return <Shell><Studio /></Shell>;
}

function Studio() {
  const { session } = useAuth();
  const toast = useToast();
  const [analysis, setAnalysis] = useState<StudioAnalysis | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [built, setBuilt] = useState<StudioBuilt | null>(null);
  const [title, setTitle] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [checks, setChecks] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [approved, setApproved] = useState(false);
  const isOwner = session?.user.role === "owner";
  const canWrite = session?.user.role !== "viewer";

  async function read(file: File | undefined) {
    if (!file) return;
    setBusy("read");
    setError("");
    try {
      const a = await api.studioAnalyze(file);
      setAnalysis(a);
      setRows(a.candidates.map((c, i) => ({ ...c, id: i })));
      setTitle(file.name.replace(/\.docx$/i, "").replace(/[_-]+/g, " ").trim());
      setBuilt(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that file.");
    } finally { setBusy(""); }
  }

  const patch = (id: number, p: Partial<Row>) => setRows((cur) => cur.map((r) => (r.id === id ? { ...r, ...p } : r)));
  const picked = rows.filter((r) => r.include);
  const badIds = picked.filter((r) => r.type !== "amount_words" && !FIELD_RX.test(r.field_id));

  async function build() {
    if (!analysis) return;
    setBusy("build");
    setError("");
    try {
      const out = await api.studioBuild({
        upload_id: analysis.upload_id, title: title.trim(), source_name: analysis.filename, jurisdiction: jurisdiction.trim() || undefined,
        add_verification_checks: checks,
        selections: picked.map((r) => ({
          text: r.text, field_id: r.field_id, label: r.label, type: r.type, required: r.required, high_impact: r.high_impact,
          occurrence: r.occurrence, link_to: r.link_to, options: r.options,
        })),
      });
      setBuilt(out);
      window.scrollTo({ top: 0 });
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Could not build the template.");
    } finally { setBusy(""); }
  }

  async function approve() {
    if (!built) return;
    setBusy("approve");
    try {
      await api.approveTemplate(built.template.id);
      setApproved(true);
      toast("Template approved. You can start jobs from it now.", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not approve.", "error");
    } finally { setBusy(""); }
  }

  // ------------------------------------------------------------ result
  if (built) {
    return (
      <div className="space-y-8">
        <div>
          <h1 className="font-display text-4xl leading-tight">{built.template.title}</h1>
          <p className="mt-1 text-muted">Version {built.template.version}. {approved ? "Approved and ready to use." : "Built, but not usable until the business owner approves it."}</p>
        </div>

        {built.problems.length > 0 && <Notice kind="warning" title="Some choices could not be applied"><ul className="list-disc pl-5">{built.problems.map((p) => <li key={p}>{p}</li>)}</ul></Notice>}

        {built.leftovers.length > 0 ? (
          <Notice kind="warning" title={`${built.leftovers.length} thing${built.leftovers.length !== 1 ? "s" : ""} still look like a previous client's details`}>
            <p>If these stay, they will appear in every new document. Go back and tick any that should change.</p>
            <ul className="mt-2 space-y-1">{built.leftovers.map((l) => <li key={l.text}><strong>{l.text}</strong> <span className="text-[0.875rem] text-ink-2">in “{l.context}”</span></li>)}</ul>
            <div className="mt-3"><Button variant="secondary" onClick={() => setBuilt(null)}>Go back and change my picks</Button></div>
          </Notice>
        ) : <Notice kind="ok">Nothing left in the wording looks like a previous client&apos;s details.</Notice>}

        <section>
          <h2 className="font-display text-2xl">What it will ask for</h2>
          <ul className="mt-2 divide-y divide-rule-soft border-y border-rule-soft">
            {built.template.fields.map((f) => <li key={f.id} className="flex justify-between gap-4 py-2"><span>{f.label}</span><span className="text-muted">{f.type}</span></li>)}
          </ul>
        </section>

        <section>
          <h2 className="mb-1 font-display text-2xl">Your wording, with blanks where details go</h2>
          <p className="mb-4 text-[0.9375rem] text-muted">Underlined labels in angle brackets are filled for each client. Everything else is your text, unchanged.</p>
          <DocumentPaper blocks={built.preview as never} docKey={built.template.id} />
        </section>

        <div className="flex flex-wrap items-center gap-4 border-t border-rule pt-5">
          {!approved && isOwner && <Button onClick={approve} busy={busy === "approve"}>Approve this template</Button>}
          {!approved && !isOwner && <p className="text-muted">A business owner needs to approve it in Templates before anyone can use it.</p>}
          {approved && <Link href="/workspaces" className="rounded-[3px] bg-cobalt px-4 py-2 font-medium text-sheet hover:bg-[#1a38b3]">Start a job from it</Link>}
          <Link href="/templates" className="underline decoration-rule underline-offset-4 hover:text-cobalt">Back to templates</Link>
        </div>
      </div>
    );
  }

  // ------------------------------------------------------------ upload
  if (!analysis) {
    return (
      <div className="max-w-[44rem] space-y-6">
        <div>
          <h1 className="font-display text-4xl leading-tight sm:text-5xl">Turn your own draft into a template</h1>
          <p className="mt-3 text-ink-2">
            Upload a past document in Word. The analyst finds the parts that change from client to client. You decide which to keep,
            and the rest of your wording stays exactly as written.
          </p>
        </div>
        {error && <Notice kind="error">{error}</Notice>}
        {!canWrite && <Notice kind="info">Your role is viewer, so you can read templates but not add them.</Notice>}
        <label className={`block border border-dashed border-ink bg-sheet px-6 py-10 text-center ${canWrite ? "cursor-pointer hover:border-cobalt" : "opacity-50"} has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-cobalt`}>
          <span className="font-display text-2xl">{busy === "read" ? "Reading your draft…" : "Choose a Word file (.docx)"}</span>
          <span className="mt-1 block text-[0.9375rem] text-muted">Use a draft with a real client&apos;s details in it. They are replaced, not kept.</span>
          <input type="file" accept=".docx" className="sr-only" disabled={!canWrite || busy === "read"} onChange={(e) => { read(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        <ul className="space-y-1 text-[0.875rem] text-muted">
          <li>The file is stored in your business&apos;s space only. Other businesses cannot see it.</li>
          <li>Nothing is sent to an AI service unless an owner has turned that on.</li>
          <li>A template cannot be used until the business owner approves it.</li>
        </ul>
      </div>
    );
  }

  // ------------------------------------------------------------ review the proposals
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl leading-tight">Which parts change for each client?</h1>
        <p className="mt-1 max-w-[62ch] text-muted">Tick the details that should be asked for every time. Anything you leave unticked stays as written in your draft.</p>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {analysis.warnings.map((w) => <Notice key={w} kind="warning">{w}</Notice>)}
      <Notice kind={analysis.agent.used ? "info" : "info"}>{analysis.agent.note}</Notice>

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink pb-2 text-[0.9375rem]">
        <span>{picked.length} of {rows.length} picked</span>
        <span className="flex gap-4">
          <button className="underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => setRows((r) => r.map((x) => ({ ...x, include: x.kind !== "blank" && x.kind !== "pin" })))}>Pick the likely ones</button>
          <button className="underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => setRows((r) => r.map((x) => ({ ...x, include: false })))}>Clear all</button>
        </span>
      </div>

      <ul className="divide-y divide-rule-soft">
        {rows.length === 0 && <li className="py-6 text-muted">Nothing was found automatically. Add {"{{ field_name }}"} where a value belongs in Word and upload again.</li>}
        {rows.map((r) => (
          <li key={r.id} className="py-4">
            <label className="flex cursor-pointer items-start gap-3">
              <input type="checkbox" className="mt-1.5 h-4 w-4 accent-cobalt" checked={r.include} onChange={(e) => patch(r.id, { include: e.target.checked })} />
              <span className="min-w-0">
                <span className="font-display text-[1.125rem]">“{r.text}”</span>
                {r.count > 1 && <span className="ml-2 text-[0.875rem] text-muted">appears {r.count} times, becomes one field</span>}
                {r.source === "agent" && <span className="ml-2 text-[0.8125rem] text-cobalt">suggested by the analyst model</span>}
                <span className="mt-0.5 block text-[0.875rem] text-muted">{r.context}</span>
                {r.note && <span className="block text-[0.875rem] text-ochre">{r.note}</span>}
              </span>
            </label>
            {r.include && r.type === "amount_words" && (
              <p className="ml-7 mt-2 text-[0.9375rem] text-ink-2">Will be spelled out from the amount it belongs to{r.link_to ? <> (<strong>{rows.find((x) => x.field_id === r.link_to)?.label ?? r.link_to}</strong>)</> : ""}, so the figure and the words always agree.</p>
            )}
            {r.include && r.type !== "amount_words" && (
              <div className="ml-7 mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_12rem]">
                <div>
                  <label htmlFor={`l${r.id}`} className="text-[0.875rem] font-medium">Question to ask</label>
                  <input id={`l${r.id}`} value={r.label} maxLength={80} onChange={(e) => patch(r.id, { label: e.target.value })} className="mt-0.5 w-full border border-rule bg-sheet px-2.5 py-1.5 outline-none focus:border-cobalt" />
                </div>
                <div>
                  <label htmlFor={`f${r.id}`} className="text-[0.875rem] font-medium">Field name</label>
                  <input id={`f${r.id}`} value={r.field_id} maxLength={41} aria-invalid={!FIELD_RX.test(r.field_id) || undefined}
                    onChange={(e) => patch(r.id, { field_id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
                    className={`mt-0.5 w-full border bg-sheet px-2.5 py-1.5 outline-none focus:border-cobalt ${FIELD_RX.test(r.field_id) ? "border-rule" : "border-danger"}`} />
                </div>
                <div>
                  <label htmlFor={`t${r.id}`} className="text-[0.875rem] font-medium">Kind of answer</label>
                  {r.type === "select" ? <p className="mt-1.5 text-[0.9375rem]">Choose from {r.options?.length} titles</p> : (
                    <select id={`t${r.id}`} value={r.type} onChange={(e) => patch(r.id, { type: e.target.value })} className="mt-0.5 w-full border border-rule bg-sheet px-2 py-1.5 outline-none focus:border-cobalt">
                      {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  )}
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-1 sm:col-span-3">
                  <label className="flex items-center gap-2 text-[0.9375rem]"><input type="checkbox" className="h-4 w-4 accent-cobalt" checked={r.required} onChange={(e) => patch(r.id, { required: e.target.checked })} />Always required</label>
                  <label className="flex items-center gap-2 text-[0.9375rem]"><input type="checkbox" className="h-4 w-4 accent-cobalt" checked={r.high_impact} onChange={(e) => patch(r.id, { high_impact: e.target.checked })} />Check this one at approval (names, amounts, dates)</label>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      <section className="space-y-4 border-t border-rule pt-6">
        <h2 className="font-display text-2xl">Name the template</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="tpl-title" className="font-medium">Template name</label>
            <input id="tpl-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} className="mt-1 w-full border border-rule bg-sheet px-3 py-2 outline-none focus:border-cobalt" />
          </div>
          <div>
            <label htmlFor="tpl-jur" className="font-medium">Jurisdiction <span className="font-normal text-muted">(optional, for your records)</span></label>
            <input id="tpl-jur" value={jurisdiction} maxLength={100} onChange={(e) => setJurisdiction(e.target.value)} className="mt-1 w-full border border-rule bg-sheet px-3 py-2 outline-none focus:border-cobalt" />
          </div>
        </div>
        <label className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-cobalt" checked={checks} onChange={(e) => setChecks(e.target.checked)} />
          <span>Make the operator confirm two checks on every case<span className="block text-[0.875rem] text-muted">That the client&apos;s identity document was verified, and that the facts were read back to the client. They are never filled in for you.</span></span>
        </label>
        {badIds.length > 0 && <Notice kind="error">Field names must be lowercase letters, digits and underscores, starting with a letter. Fix {badIds.length} highlighted name{badIds.length !== 1 ? "s" : ""}.</Notice>}
        <div className="flex flex-wrap gap-4">
          <Button onClick={build} busy={busy === "build"} disabled={!canWrite || picked.length === 0 || title.trim().length < 3 || badIds.length > 0}>Build the template</Button>
          <Button variant="quiet" onClick={() => { setAnalysis(null); setRows([]); }}>Use a different file</Button>
        </div>
      </section>
    </div>
  );
}
