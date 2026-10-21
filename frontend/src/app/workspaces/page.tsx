"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type WorkspaceInfo } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Button, EmptyState, Notice, Spinner } from "@/components/ui";
import { Stage } from "@/components/scene/Stage";
import type { Material } from "@/components/scene/paper";
import { MATERIAL_FOR } from "@/lib/workspaces";
import { useAuth } from "@/lib/auth";

export default function Workspaces() {
  const { session } = useAuth();
  const router = useRouter();
  const [list, setList] = useState<WorkspaceInfo[] | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState<string>("");
  const [starting, setStarting] = useState("");
  const key = useRef(crypto.randomUUID());

  useEffect(() => {
    if (!session) return;
    api.workspaces().then((w) => { setList(w); setActive(window.location.hash.slice(1) || w[0].id); }).catch((e) => setError(e.message));
  }, [session]);

  async function start(id: string) {
    setStarting(id);
    try {
      // The idempotency key makes a double click return the same case instead of creating two.
      const c = await api.createCase(id, `${key.current}-${id}`);
      router.push(`/desk/${c.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the job.");
      setStarting("");
      key.current = crypto.randomUUID();
    }
  }

  const material = (MATERIAL_FOR[active] ?? "home") as Material;
  const canWrite = session?.user.role !== "viewer";

  return (
    <Shell wide>
      <div className="mx-auto grid max-w-[1280px] gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <h1 className="font-display text-4xl leading-tight sm:text-5xl">What are you preparing today?</h1>
          <p className="mt-2 max-w-[52ch] text-muted">Pick the kind of work. You will describe the job next, by voice or in writing.</p>
          {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
          {!canWrite && <div className="mt-4"><Notice kind="info">Your role is viewer, so you can browse but not start jobs.</Notice></div>}

          {!list && !error && <p className="mt-10 flex items-center gap-2 text-muted"><Spinner /> Loading workspaces…</p>}
          {list && list.length === 0 && <div className="mt-8"><EmptyState title="No workspaces are configured" /></div>}

          <ul className="mt-8 divide-y divide-rule border-y border-rule">
            {list?.map((w) => (
              <li key={w.id} id={w.id} onMouseEnter={() => setActive(w.id)} onFocus={() => setActive(w.id)}
                className={`grid gap-4 px-1 py-6 transition-colors sm:grid-cols-[1fr_auto] ${active === w.id ? "bg-sheet/60" : ""}`}>
                <div>
                  <h2 className="font-display text-[1.75rem] leading-tight">{w.name}</h2>
                  <p className="mt-1 max-w-[56ch] text-ink-2">{w.description}</p>
                  <p className="mt-3 text-[0.9375rem] text-muted">
                    Produces: {w.documents.map((d) => d.title).join(", ")}.
                  </p>
                  {w.other_workflows.length > 0 && (
                    <p className="mt-1 text-[0.875rem] text-muted">Not available yet: {w.other_workflows.join(", ")}.</p>
                  )}
                </div>
                <div className="sm:self-center">
                  <Button onClick={() => start(w.id)} busy={starting === w.id} disabled={!canWrite || !!starting}>Start a job</Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="hidden lg:block">
          <div className="sticky top-8 h-[min(72dvh,640px)]">
            <Stage material={material} intro={false} className="h-full" label="Sheets arranged to match the highlighted workspace" />
          </div>
        </div>
      </div>
    </Shell>
  );
}
