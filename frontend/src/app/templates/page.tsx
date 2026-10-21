"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type TemplateInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { Button, Notice, Spinner, useToast } from "@/components/ui";
import { DocumentPaper } from "@/features/desk/DocumentPaper";
import { WORKSPACE_BRIEFS } from "@/lib/workspaces";

export default function Templates() {
  return <Shell><TemplatesInner /></Shell>;
}

function TemplatesInner() {
  const { session } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const [items, setItems] = useState<TemplateInfo[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string>("");
  const [blocks, setBlocks] = useState<Record<string, unknown>[] | null>(null);
  const [busy, setBusy] = useState("");
  const key = useRef(crypto.randomUUID());
  const isOwner = session?.user.role === "owner";
  const canWrite = session?.user.role !== "viewer";

  const load = useCallback(() => { api.templates().then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(() => { if (session) load(); }, [session, load]);

  async function togglePreview(t: TemplateInfo) {
    if (open === t.id) { setOpen(""); return; }
    setOpen(t.id);
    setBlocks(null);
    try { setBlocks((await api.templatePreview(t.id)).blocks); } catch (e) { toast(e instanceof Error ? e.message : "Could not load the preview.", "error"); }
  }

  async function act(t: TemplateInfo, what: "approve" | "retire") {
    setBusy(`${what}${t.id}`);
    try {
      await (what === "approve" ? api.approveTemplate(t.id) : api.retireTemplate(t.id));
      toast(what === "approve" ? "Template approved." : "Template retired. It can no longer start new cases.", "ok");
      load();
    } catch (e) { toast(e instanceof Error ? e.message : "That did not work.", "error"); } finally { setBusy(""); }
  }

  async function start(t: TemplateInfo) {
    setBusy(`start${t.id}`);
    try {
      const c = await api.createCase("custom", `${key.current}-${t.key}`, t.key);
      router.push(`/desk/${c.id}`);
    } catch (e) { toast(e instanceof Error ? e.message : "Could not start the job.", "error"); setBusy(""); key.current = crypto.randomUUID(); }
  }

  const mine = items?.filter((t) => t.owned_by_business) ?? [];

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-tight">Templates</h1>
          <p className="mt-1 max-w-[62ch] text-muted">The wording that drafts are built from. Only approved versions are used, and the newest approved version wins.</p>
        </div>
        {canWrite && <Link href="/templates/new" className="rounded-[3px] bg-cobalt px-4 py-2 font-medium text-sheet hover:bg-[#1a38b3]">Add your own template</Link>}
      </div>
      {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
      {!items && !error && <p className="mt-10 flex items-center gap-2 text-muted"><Spinner /> Loading templates…</p>}

      {items && (
        <section className="mt-10">
          <h2 className="font-display text-2xl">Your business&apos;s templates</h2>
          {mine.length === 0 ? (
            <p className="mt-2 max-w-[62ch] text-muted">None yet. Upload a past draft and the studio turns it into a template in your own wording.</p>
          ) : (
            <ul className="mt-3 divide-y divide-rule-soft border-y border-rule-soft">
              {mine.map((t) => (
                <li key={t.id} className="py-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-medium">{t.title} <span className="font-normal text-muted">version {t.version}</span></p>
                      <p className="text-[0.875rem]"><span className={t.approved ? "text-ok" : "text-ochre"}>{t.approved ? "Approved" : "Waiting for approval"}</span> <span className="text-muted">{t.fields.length} details asked each time</span></p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <Button variant="quiet" onClick={() => togglePreview(t)}>{open === t.id ? "Hide wording" : "See the wording"}</Button>
                      {isOwner && !t.approved && <Button onClick={() => act(t, "approve")} busy={busy === `approve${t.id}`}>Approve</Button>}
                      {isOwner && t.approved && <Button variant="secondary" onClick={() => act(t, "retire")} busy={busy === `retire${t.id}`}>Retire</Button>}
                      {t.approved && canWrite && <Button onClick={() => start(t)} busy={busy === `start${t.id}`}>Start a job</Button>}
                    </div>
                  </div>
                  {!t.approved && !isOwner && <p className="mt-1 text-[0.875rem] text-muted">A business owner needs to approve this before it can be used.</p>}
                  {open === t.id && (
                    <div className="mt-4">{blocks ? <DocumentPaper blocks={blocks as never} docKey={t.id} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="mt-8"><Notice kind="warning" title="Bundled demonstration templates">
        The templates below are samples. Replace them with wording your business has approved before using drafts for real clients.
      </Notice></div>
      {items && WORKSPACE_BRIEFS.map((w) => {
        const rows = items.filter((t) => t.workspace === w.id && !t.owned_by_business);
        if (!rows.length) return null;
        return (
          <section key={w.id} className="mt-10">
            <h2 className="font-display text-2xl">{w.name}</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-left text-[0.9375rem]">
                <caption className="sr-only">{w.name} templates</caption>
                <thead>
                  <tr className="border-b-2 border-ink text-[0.875rem]">
                    <th scope="col" className="py-2 pr-4 font-semibold">Template</th>
                    <th scope="col" className="py-2 pr-4 font-semibold">Version</th>
                    <th scope="col" className="py-2 pr-4 font-semibold">State</th>
                    <th scope="col" className="py-2 font-semibold">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.id} className="border-b border-rule-soft align-top">
                      <th scope="row" className="py-3 pr-4 text-left font-medium">{t.title}<span className="block text-[0.8125rem] font-normal text-muted">{t.key}</span></th>
                      <td className="py-3 pr-4">{t.version}</td>
                      <td className="py-3 pr-4">
                        <span className={t.approved ? "text-ok" : "text-muted"}>{t.approved ? "Approved" : "Superseded"}</span>
                        {t.is_demo && <span className="block text-[0.8125rem] text-ochre">Demonstration</span>}
                      </td>
                      <td className="py-3 text-muted">
                        {t.note}
                        {t.verify_fields.length > 0 && <span className="block text-[0.8125rem]">Operator must verify: {t.verify_fields.length} checks</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </>
  );
}
