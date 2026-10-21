"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, streamEvents, type CaseOut, type WorkflowEvent } from "@/lib/api";
import { ManifestRejected, type Manifest } from "@/lib/manifest";

const WITH_MANIFEST = new Set(["awaiting_input", "review", "approved", "exported"]);

export interface CaseState {
  data: CaseOut | null;
  manifest: Manifest | null;
  events: WorkflowEvent[];
  loading: boolean;
  error: string;
  /** Re-reads the case and its manifest. `view="review"` re-opens an approved case read-only. */
  refresh: (view?: string) => Promise<void>;
  apply: (c: CaseOut) => Promise<void>;
}

/** Everything the desk needs about one case: live status, the current UI manifest and progress events. */
export function useCase(id: string, view?: string): CaseState {
  const [data, setData] = useState<CaseOut | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const viewRef = useRef(view);
  viewRef.current = view;
  const alive = useRef(true);

  const load = useCallback(async (caseData?: CaseOut, v?: string) => {
    try {
      const c = caseData ?? (await api.getCase(id));
      if (!alive.current) return;
      setData(c);
      if (WITH_MANIFEST.has(c.status)) setManifest(await api.manifest(id, v ?? viewRef.current));
      else setManifest(null);
      setError("");
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof ManifestRejected || e instanceof Error ? e.message : "Something went wrong.");
      if (e instanceof ApiError && e.status === 404) setData(null);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    let stop = () => {};
    (async () => {
      await load();
      const past = await api.events(id).catch(() => []);
      if (!alive.current) return;
      setEvents(past);
      stop = streamEvents(id, (e) => {
        setEvents((cur) => (cur.some((x) => x.id === e.id) ? cur : [...cur, e]));
        if (["missing_fields", "approval_required", "workflow_error", "export_ready", "approved", "cancelled"].includes(e.type)) load();
      }, past.at(-1)?.id ?? 0);
    })();
    return () => { alive.current = false; stop(); };
  }, [id, load]);

  // The server finishes extraction in the background; poll lightly so the screen cannot get stuck.
  useEffect(() => {
    if (data?.status !== "processing") return;
    const t = setInterval(() => load(), 1500);
    return () => clearInterval(t);
  }, [data?.status, load]);

  return { data, manifest, events, loading, error, refresh: (v) => load(undefined, v), apply: (c) => load(c) };
}
