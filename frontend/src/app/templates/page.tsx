"use client";

import { useEffect, useState } from "react";
import { api, type TemplateInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { Notice, Spinner } from "@/components/ui";
import { WORKSPACE_BRIEFS } from "@/lib/workspaces";

export default function Templates() {
  const { session } = useAuth();
  const [items, setItems] = useState<TemplateInfo[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (session) api.templates().then(setItems).catch((e) => setError(e.message)); }, [session]);

  return (
    <Shell>
      <h1 className="font-display text-4xl leading-tight">Templates</h1>
      <p className="mt-1 max-w-[62ch] text-muted">
        The wording that drafts are built from. Only approved versions are used, and the newest approved version wins.
      </p>
      <div className="mt-4"><Notice kind="warning" title="Demonstration templates">
        The bundled templates are samples. Replace them with wording your business has approved before using drafts for real clients.
      </Notice></div>
      {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
      {!items && !error && <p className="mt-10 flex items-center gap-2 text-muted"><Spinner /> Loading templates…</p>}
      {items && WORKSPACE_BRIEFS.map((w) => {
        const rows = items.filter((t) => t.workspace === w.id);
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
    </Shell>
  );
}
