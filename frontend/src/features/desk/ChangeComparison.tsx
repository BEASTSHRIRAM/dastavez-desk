"use client";

import { MarkedText } from "./DocumentPaper";

interface Section { approved: string; draft: string; changed: boolean }

/** Approved template wording beside the draft. Only sections where a placeholder was filled count as changed. */
export function ChangeComparison({ title, sections }: { title: string; sections: Section[] }) {
  const changed = sections.filter((s) => s.changed);
  const kept = sections.filter((s) => !s.changed);
  return (
    <section aria-label={`Changes from the approved template for ${title}`} className="space-y-3">
      <div>
        <h3 className="font-display text-xl">What changed from the approved template</h3>
        <p className="text-[0.9375rem] text-muted">
          {changed.length} section{changed.length !== 1 ? "s" : ""} filled in. {kept.length} section{kept.length !== 1 ? "s" : ""} of approved wording kept exactly as written.
        </p>
      </div>
      {changed.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-left text-[0.9375rem]">
            <thead>
              <tr className="border-b-2 border-ink">
                <th scope="col" className="w-1/2 py-2 pr-4 font-semibold">Approved template</th>
                <th scope="col" className="py-2 font-semibold">This draft</th>
              </tr>
            </thead>
            <tbody>
              {changed.map((s, i) => (
                <tr key={i} className="border-b border-rule-soft align-top">
                  <td className="py-2.5 pr-4 text-muted"><span className="doc">{s.approved}</span></td>
                  <td className="py-2.5"><span className="doc"><MarkedText text={s.draft} /></span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {kept.length > 0 && (
        <details className="text-[0.9375rem]">
          <summary className="cursor-pointer underline decoration-rule underline-offset-4 hover:text-cobalt">Show the {kept.length} unchanged sections</summary>
          <ul className="mt-2 space-y-1.5 border-l-2 border-rule-soft pl-4">
            {kept.map((s, i) => <li key={i} className="doc text-ink-2">{s.approved}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}
