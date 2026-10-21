"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type CaseRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { Button, ConfirmDialog, EmptyState, Notice, Spinner, StatusPill } from "@/components/ui";
import { WORKSPACE_BRIEFS } from "@/lib/workspaces";

const NAMES = Object.fromEntries(WORKSPACE_BRIEFS.map((w) => [w.id, w.name]));
const fmt = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Cases() {
  const { session } = useAuth();
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [error, setError] = useState("");
  const [toDelete, setToDelete] = useState<CaseRow | null>(null);

  const load = useCallback(() => {
    api.cases().then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { if (session) load(); }, [session, load]);

  async function confirmDelete() {
    if (!toDelete) return;
    try {
      await api.remove(toDelete.id);
      setToDelete(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the case.");
      setToDelete(null);
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-tight">Cases</h1>
          <p className="mt-1 text-muted">Every job for {session?.business.name}, newest first.</p>
        </div>
        <Link href="/workspaces" className="rounded-[3px] bg-cobalt px-4 py-2 font-medium text-sheet hover:bg-[#1a38b3]">New job</Link>
      </div>
      {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
      {!rows && !error && <p className="mt-10 flex items-center gap-2 text-muted"><Spinner /> Loading cases…</p>}
      {rows?.length === 0 && (
        <div className="mt-8"><EmptyState title="No cases yet" action={<Link href="/workspaces" className="text-cobalt underline underline-offset-4">Start your first job</Link>}>
          Cases appear here as soon as you start one.
        </EmptyState></div>
      )}
      {rows && rows.length > 0 && (
        <div className="mt-8 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left">
            <caption className="sr-only">Cases</caption>
            <thead>
              <tr className="border-b-2 border-ink text-[0.875rem]">
                <th scope="col" className="py-2 pr-4 font-semibold">Case</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Workspace</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Status</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Updated</th>
                <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-b border-rule-soft align-middle">
                  <td className="py-3 pr-4"><Link href={`/desk/${c.id}`} className="font-medium underline decoration-rule underline-offset-4 hover:text-cobalt hover:decoration-cobalt">{c.title}</Link></td>
                  <td className="py-3 pr-4 text-ink-2">{NAMES[c.workspace] ?? c.workspace}</td>
                  <td className="py-3 pr-4"><StatusPill status={c.status} /></td>
                  <td className="py-3 pr-4 text-[0.9375rem] text-muted">{fmt(c.updated_at)}</td>
                  <td className="py-3 text-right">
                    {session?.user.role === "owner" && <Button variant="quiet" onClick={() => setToDelete(c)} aria-label={`Delete ${c.title}`}>Delete</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-6 max-w-[60ch] text-[0.875rem] text-muted">
        Access follows your role. Only owners can delete a case. Deleting removes its answers, uploads and exported files for good; a record that a deletion happened stays in the audit log.
      </p>
      <ConfirmDialog open={!!toDelete} danger title="Delete this case?" confirmLabel="Delete permanently"
        body={<>This removes <strong>{toDelete?.title}</strong>, its uploads and every exported file. This cannot be undone.</>}
        onConfirm={confirmDelete} onCancel={() => setToDelete(null)} />
    </Shell>
  );
}
