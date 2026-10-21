"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { Stage } from "@/components/scene/Stage";
import type { Material } from "@/components/scene/paper";
import { Wordmark } from "@/components/Shell";
import { WORKSPACE_BRIEFS } from "@/lib/workspaces";
import { useAuth } from "@/lib/auth";

gsap.registerPlugin(useGSAP, ScrollTrigger);

const STEPS = [
  ["Say it", "Hold the microphone and describe the job, or type it."],
  ["Check what was heard", "Every value shows the words it came from."],
  ["Answer the gaps", "Only the missing or uncertain details are asked."],
  ["Approve", "You confirm the values that matter. Nothing exports before this."],
  ["Export", "Download the files. The audit trail stays with the case."],
];

const LIMITS = [
  "It prepares drafts from your approved templates. It does not give legal advice or sign, stamp or notarise anything.",
  "It never submits an application, makes a booking or moves money.",
  "Requirements are shown only with a source and a last-verified date.",
];

export default function Landing() {
  const [material, setMaterial] = useState<Material>("home");
  const root = useRef<HTMLDivElement>(null);
  const { session } = useAuth();

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // One orchestrated moment: headline lines rise after the sheets have landed.
        gsap.from("[data-line]", { yPercent: 110, duration: 1, ease: "expo.out", stagger: 0.12, delay: 0.5 });
        gsap.from("[data-fade]", { opacity: 0, y: 12, duration: 0.8, ease: "power2.out", stagger: 0.1, delay: 1.1 });
        gsap.fromTo("[data-rule]", { scaleX: 0 }, {
          scaleX: 1, transformOrigin: "left center", ease: "none",
          scrollTrigger: { trigger: "[data-steps]", start: "top 80%", end: "bottom 70%", scrub: true },
        });
      });
      return () => mm.revert();
    },
    { scope: root },
  );

  return (
    <div ref={root}>
      <section className="relative lg:min-h-dvh">
        <Stage material={material} shift={0.3} className="h-[44vh] lg:absolute lg:inset-0 lg:h-auto" label="Document sheets arranged for the selected workspace" />
        <div className="pointer-events-none relative z-10 mx-auto flex w-full max-w-[1280px] flex-col px-5 pb-8 pt-5 sm:px-10 lg:min-h-dvh">
          <header className="pointer-events-auto flex items-center justify-between">
            <Wordmark />
            <Link href={session ? "/workspaces" : "/login"} className="text-[0.9375rem] underline decoration-rule underline-offset-4 hover:text-cobalt hover:decoration-cobalt">
              {session ? "Open the desk" : "Sign in"}
            </Link>
          </header>

          <div className="my-10 max-w-[36rem] lg:my-auto lg:py-16">
            <h1 className="font-display text-[clamp(2.7rem,6.4vw,5.4rem)] font-medium leading-[0.98] tracking-[-0.02em]" style={{ fontVariationSettings: '"opsz" 72' }}>
              {["Speak once.", "Review everything.", "Print ready."].map((l) => (
                <span key={l} className="block overflow-hidden pb-[0.06em]"><span data-line className="block">{l}</span></span>
              ))}
            </h1>
            <p data-fade className="mt-6 max-w-[34rem] text-[1.0625rem] text-ink-2">
              Dastavez Desk listens to the job, builds a document from your approved template, and asks only for what is
              missing. You review every value before anything is exported.
            </p>
            <div data-fade className="pointer-events-auto mt-8 flex flex-wrap items-center gap-5">
              <Link href="/workspaces" className="inline-flex items-center gap-2 rounded-[3px] bg-cobalt px-6 py-3 text-[1.0625rem] font-medium text-sheet transition-colors hover:bg-[#1a38b3]">
                <MicIcon /> Start by speaking
              </Link>
              <span className="text-[0.9375rem] text-muted">Typing works too.</span>
            </div>
          </div>

          <nav data-fade aria-label="Workspaces" className="pointer-events-auto grid gap-px border-t border-rule bg-rule sm:grid-cols-2 lg:grid-cols-5">
            {WORKSPACE_BRIEFS.map((w) => (
              <Link key={w.id} href={`/workspaces#${w.id}`}
                onMouseEnter={() => setMaterial(w.material)} onFocus={() => setMaterial(w.material)}
                onMouseLeave={() => setMaterial("home")} onBlur={() => setMaterial("home")}
                className="group bg-paper/90 px-4 py-4 backdrop-blur-[2px] transition-colors hover:bg-sheet focus-visible:bg-sheet">
                <span className="block font-display text-[1.2rem] leading-tight">{w.name}</span>
                <span className="mt-1 block text-[0.875rem] text-muted group-hover:text-ink-2">{w.line}</span>
              </Link>
            ))}
          </nav>
        </div>
      </section>

      <section className="mx-auto max-w-[1280px] px-5 py-20 sm:px-10">
        <h2 className="font-display text-3xl leading-tight sm:text-4xl">How a job runs</h2>
        <div data-steps className="relative mt-10">
          <div className="absolute left-0 right-0 top-0 h-px bg-rule-soft" />
          <div data-rule className="absolute left-0 right-0 top-0 h-[2px] bg-cobalt" />
          <ol className="grid gap-8 pt-6 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map(([t, d], i) => (
              <li key={t}>
                <p className="font-display text-[1.25rem]"><span className="text-cobalt">{i + 1}.</span> {t}</p>
                <p className="mt-1 text-[0.9375rem] text-muted">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="bg-ink px-5 py-16 text-sheet sm:px-10">
        <div className="mx-auto grid max-w-[1280px] gap-10 lg:grid-cols-[1fr_1.2fr]">
          <h2 className="font-display text-3xl leading-tight sm:text-4xl">What it will not do</h2>
          <ul className="space-y-4 text-[1.0625rem] text-sheet/85">
            {LIMITS.map((l) => <li key={l} className="border-t border-sheet/20 pt-4">{l}</li>)}
          </ul>
        </div>
      </section>
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}
