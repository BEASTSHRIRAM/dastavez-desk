"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-cobalt text-sheet hover:bg-[#1a38b3] disabled:bg-rule disabled:text-muted",
  secondary: "border border-ink text-ink hover:bg-ink hover:text-sheet disabled:border-rule disabled:text-muted disabled:hover:bg-transparent",
  quiet: "text-ink underline decoration-rule underline-offset-4 hover:decoration-cobalt hover:text-cobalt disabled:text-muted",
  danger: "border border-danger text-danger hover:bg-danger hover:text-sheet disabled:border-rule disabled:text-muted",
};

export function Button({ variant = "primary", busy = false, className = "", children, disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-[3px] px-4 py-2 text-[0.9375rem] font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`h-4 w-4 animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity=".25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

const STATUS: Record<string, { label: string; cls: string }> = {
  intake: { label: "Not started", cls: "bg-rule-soft text-ink-2" },
  processing: { label: "Working", cls: "bg-cobalt-soft text-cobalt" },
  awaiting_input: { label: "Needs your answers", cls: "bg-ochre-soft text-ochre" },
  review: { label: "Ready to review", cls: "bg-cobalt-soft text-cobalt" },
  approved: { label: "Approved", cls: "bg-ok-soft text-ok" },
  exported: { label: "Exported", cls: "bg-ok-soft text-ok" },
  cancelled: { label: "Cancelled", cls: "bg-rule-soft text-muted" },
  failed: { label: "Stopped by an error", cls: "bg-danger-soft text-danger" },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-rule-soft text-ink-2" };
  return <span className={`inline-block rounded-[3px] px-2 py-0.5 text-[0.8125rem] font-medium ${s.cls}`}>{s.label}</span>;
}

export function Notice({ kind = "info", title, children }: { kind?: "info" | "warning" | "error" | "ok"; title?: string; children?: ReactNode }) {
  const cls = {
    info: "border-cobalt bg-cobalt-soft",
    warning: "border-ochre bg-ochre-soft",
    error: "border-danger bg-danger-soft",
    ok: "border-ok bg-ok-soft",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`border-l-[3px] px-4 py-3 text-[0.9375rem] ${cls}`}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-0.5" : ""}>{children}</div>}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="border border-dashed border-rule px-6 py-10">
      <p className="font-display text-xl">{title}</p>
      {children && <p className="mt-1 max-w-[52ch] text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ toasts
interface Toast { id: number; kind: "info" | "error" | "ok"; text: string }
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((cur) => [...cur.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), kind === "error" ? 9000 : 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="no-print pointer-events-none fixed bottom-4 right-4 z-50 flex max-w-[min(420px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto border-l-[3px] bg-sheet px-4 py-3 text-[0.9375rem] shadow-[0_6px_24px_-10px_rgba(20,23,31,.5)] ${t.kind === "error" ? "border-danger" : t.kind === "ok" ? "border-ok" : "border-cobalt"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ------------------------------------------------------------------ confirm dialog (native <dialog>: focus trap and Esc for free)
export function ConfirmDialog({ open, title, body, confirmLabel, onConfirm, onCancel, danger = false }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void; danger?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} aria-labelledby={id} onClose={onCancel} onCancel={onCancel}
      className="m-auto w-[min(440px,calc(100vw-2rem))] border border-ink bg-sheet p-0 text-ink backdrop:bg-ink/50">
      <div className="p-6">
        <h2 id={id} className="font-display text-2xl">{title}</h2>
        <div className="mt-2 text-muted">{body}</div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="quiet" onClick={onCancel}>Keep it</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </dialog>
  );
}
