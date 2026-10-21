"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth";
import { Button, Notice } from "@/components/ui";
import { Wordmark } from "@/components/Shell";

const DEMO = [
  { label: "Operator", email: "operator@demo.test" },
  { label: "Owner", email: "owner@demo.test" },
  { label: "Viewer", email: "viewer@demo.test" },
  { label: "Other business", email: "other@demo.test" },
];

export default function Login() {
  const { login, session, ready } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && session) router.replace("/workspaces");
  }, [ready, session, router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
      router.replace("/workspaces");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="mx-auto grid min-h-dvh max-w-[960px] content-center gap-10 px-5 py-10 md:grid-cols-[1fr_1fr]">
      <div className="space-y-4 self-end">
        <Wordmark />
        <h1 className="font-display text-4xl leading-tight">Sign in to your desk</h1>
        <p className="max-w-[34ch] text-muted">Your business&apos;s cases, saved records and templates stay inside your business.</p>
      </div>
      <form onSubmit={submit} className="space-y-4 border border-rule bg-sheet p-6" noValidate>
        {error && <Notice kind="error">{error}</Notice>}
        <div>
          <label htmlFor="email" className="mb-1 block text-[0.9375rem] font-medium">Email</label>
          <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-rule bg-paper/40 px-3 py-2 outline-none focus:border-cobalt" />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-[0.9375rem] font-medium">Password</label>
          <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-rule bg-paper/40 px-3 py-2 outline-none focus:border-cobalt" />
        </div>
        <Button type="submit" busy={busy} className="w-full">Sign in</Button>
        <div className="border-t border-rule-soft pt-4 text-[0.875rem] text-muted">
          <p className="font-medium text-ink">Demonstration accounts</p>
          <p>Fictional data only. Password for all: <span className="font-medium text-ink">demo-pass</span></p>
          <div className="mt-2 flex flex-wrap gap-2">
            {DEMO.map((d) => (
              <button key={d.email} type="button" onClick={() => { setEmail(d.email); setPassword("demo-pass"); }}
                className="rounded-[3px] border border-rule px-2.5 py-1 hover:border-cobalt hover:text-cobalt">
                {d.label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </main>
  );
}
