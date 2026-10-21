"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAuth, useRequireAuth } from "@/lib/auth";
import { ToastProvider } from "./ui";
import { useReduce3D } from "./scene/Stage";

const NAV = [
  { href: "/workspaces", label: "New job" },
  { href: "/cases", label: "Cases" },
  { href: "/templates", label: "Templates" },
];

export function Wordmark({ onDark = false }: { onDark?: boolean }) {
  return (
    <Link href="/" className={`font-display text-[1.45rem] leading-none tracking-tight ${onDark ? "text-sheet" : "text-ink"}`} style={{ fontVariationSettings: '"opsz" 36' }}>
      Dastavez <span className="italic">Desk</span>
    </Link>
  );
}

/** Authenticated frame: a slim ink rail on the left, the working area on the right. */
export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const session = useRequireAuth();
  const { logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const { reduced, setReduced } = useReduce3D();
  const [open, setOpen] = useState(false);

  if (!session) return <div className="grid min-h-dvh place-items-center text-muted">Checking your session…</div>;

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.map((n) => {
        const active = pathname === n.href || (n.href === "/cases" && pathname.startsWith("/desk"));
        return (
          <Link key={n.href} href={n.href} onClick={() => setOpen(false)} aria-current={active ? "page" : undefined}
            className={`rounded-[3px] px-3 py-2 text-[0.9375rem] transition-colors ${active ? "bg-sheet text-ink" : "text-sheet/80 hover:bg-sheet/10 hover:text-sheet"}`}>
            {n.label}
          </Link>
        );
      })}
    </nav>
  );

  const account = (
    <div className="space-y-3 text-[0.8125rem] text-sheet/70">
      <div>
        <p className="font-medium text-sheet">{session.user.name}</p>
        <p>{session.user.role}, {session.business.name}</p>
      </div>
      <label className="flex cursor-pointer items-center gap-2">
        <input type="checkbox" checked={reduced} onChange={(e) => setReduced(e.target.checked)} className="h-4 w-4 accent-cobalt" />
        Reduce 3D and motion
      </label>
      <button onClick={() => { logout(); router.push("/login"); }} className="underline decoration-sheet/30 underline-offset-4 hover:text-sheet hover:decoration-sheet">
        Sign out
      </button>
    </div>
  );

  return (
    <ToastProvider>
      <div className="min-h-dvh lg:grid lg:grid-cols-[220px_1fr]">
        <aside className="no-print hidden flex-col justify-between bg-ink px-4 py-6 lg:flex lg:sticky lg:top-0 lg:h-dvh">
          <div className="space-y-8">
            <div className="px-3"><Wordmark onDark /></div>
            {nav}
          </div>
          <div className="px-3">{account}</div>
        </aside>
        <header className="no-print flex items-center justify-between bg-ink px-4 py-3 lg:hidden">
          <Wordmark onDark />
          <button aria-expanded={open} aria-controls="mobile-menu" onClick={() => setOpen(!open)} className="rounded-[3px] border border-sheet/40 px-3 py-1.5 text-sm text-sheet">
            Menu
          </button>
        </header>
        {open && (
          <div id="mobile-menu" className="no-print space-y-6 bg-ink px-4 pb-6 lg:hidden">
            {nav}
            {account}
          </div>
        )}
        <main id="main" className={`min-w-0 px-4 py-6 sm:px-8 lg:py-8 ${wide ? "" : "mx-auto w-full max-w-[1180px]"}`}>{children}</main>
      </div>
    </ToastProvider>
  );
}
