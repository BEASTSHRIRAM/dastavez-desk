"use client";

import { Fragment, useRef } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import type { PreviewBlock } from "@/lib/manifest";

gsap.registerPlugin(useGSAP);

const MARK = /⟦([^¦⟧]+)¦([^⟧]*)⟧/g;

/** Text with ⟦field¦value⟧ markers: each filled value becomes a pencil-underlined button that jumps to its input. */
export function MarkedText({ text, onFieldClick, states }: { text: string; onFieldClick?: (id: string) => void; states?: Record<string, string> }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MARK)) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const [, field, value] = m;
    const state = value.includes("[missing]") ? "missing" : (states?.[field] ?? "confirmed");
    const label = `${value}. Edit ${field.replace(/_/g, " ")}`;
    parts.push(
      onFieldClick ? (
        <button key={m.index} type="button" className="filled" data-state={state} aria-label={label} onClick={() => onFieldClick(field)}>{value}</button>
      ) : (
        <span key={m.index} className="filled" data-state={state}>{value}</span>
      ),
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</>;
}

interface Props {
  blocks: PreviewBlock[];
  docKey: string;
  onFieldClick?: (id: string) => void;
  states?: Record<string, string>;
}

export function DocumentPaper({ blocks, docKey, onFieldClick, states }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  // Progressive rendering: lines settle onto the sheet in order. Skipped for reduced motion.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const items = gsap.utils.toArray<HTMLElement>("[data-block]");
        gsap.from(items, { opacity: 0, y: 8, duration: 0.4, ease: "power2.out", stagger: Math.min(0.05, 0.9 / Math.max(items.length, 1)) });
      });
      return () => mm.revert();
    },
    { scope: ref, dependencies: [docKey], revertOnUpdate: true },
  );

  const header = blocks.find((b) => b.type === "header");
  const footer = blocks.find((b) => b.type === "footer");
  const body = blocks.filter((b) => b.type !== "header" && b.type !== "footer");
  const groups: (PreviewBlock | PreviewBlock[])[] = [];
  for (const b of body) {
    const prev = groups.at(-1);
    if (b.type === "bullet" && Array.isArray(prev)) prev.push(b);
    else if (b.type === "bullet") groups.push([b]);
    else groups.push(b);
  }
  const t = (s?: string) => <MarkedText text={s ?? ""} onFieldClick={onFieldClick} states={states} />;

  return (
    <article ref={ref} aria-label="Document preview" className="doc mx-auto w-full max-w-[46rem] border border-rule bg-sheet px-[clamp(1.25rem,5vw,3.5rem)] py-10 shadow-[0_18px_40px_-26px_rgba(20,23,31,.55)]">
      {header?.text && <p className="mb-8 border-b border-rule pb-2 font-sans text-[0.75rem] font-medium text-ochre">{header.text}</p>}
      <div className="space-y-4">
        {groups.map((g, i) => {
          if (Array.isArray(g)) {
            return <ul key={i} data-block className="list-disc space-y-1 pl-6">{g.map((b, j) => <li key={j}>{t(b.text)}</li>)}</ul>;
          }
          switch (g.type) {
            case "title": return <h1 key={i} data-block className="pb-2 text-center">{t(g.text)}</h1>;
            case "heading": return <h2 key={i} data-block className="pt-3 text-[1.2rem] font-semibold">{t(g.text)}</h2>;
            case "table": {
              const rows = g.rows ?? [];
              const head = (g as { header?: boolean }).header;
              return (
                <div key={i} data-block className="overflow-x-auto">
                  <table className="w-full border-collapse font-sans text-[0.9375rem]">
                    {head && <thead><tr>{rows[0].map((c, k) => <th key={k} scope="col" className="border-b-2 border-ink px-2 py-1.5 text-left font-semibold">{c}</th>)}</tr></thead>}
                    <tbody>
                      {rows.slice(head ? 1 : 0).map((r, k) => (
                        <tr key={k} className="border-b border-rule-soft">
                          {r.map((c, m) => m === 0 && !head
                            ? <th key={m} scope="row" className="w-[34%] px-2 py-1.5 text-left font-medium text-ink-2">{c}</th>
                            : <td key={m} className="px-2 py-1.5">{t(c)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            }
            default:
              return <p key={i} data-block className={g.note ? "font-sans text-[0.875rem] italic text-muted" : ""}>{t(g.text)}</p>;
          }
        })}
      </div>
      {footer?.text && <p className="mt-10 border-t border-rule pt-2 font-sans text-[0.75rem] text-muted">{footer.text}</p>}
    </article>
  );
}
