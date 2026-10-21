"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, getToken, setToken, type Session } from "./api";

interface AuthValue {
  session: Session | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setSession(null);
      setReady(true);
      return;
    }
    try {
      setSession(await api.me());
    } catch {
      setSession(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      session,
      ready,
      refresh,
      login: async (email, password) => {
        const { token, ...s } = await api.login(email, password);
        setToken(token);
        setSession(s);
      },
      logout: () => {
        setToken(null);
        setSession(null);
      },
    }),
    [session, ready, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}

/** Redirects to sign-in when there is no session. Returns the session once known. */
export function useRequireAuth(): Session | null {
  const { session, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (ready && !session) router.replace("/login");
  }, [ready, session, router]);
  return session;
}
