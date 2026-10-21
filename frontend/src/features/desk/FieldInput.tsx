"use client";

import { useId } from "react";
import type { FieldComponent } from "@/lib/manifest";

export type Raw = string | string[];

/** Client-side validation for fast feedback. The server validates every submitted value again. */
export function validateField(f: FieldComponent, value: Raw | undefined): string | null {
  const v = value ?? "";
  const empty = Array.isArray(v) ? v.length === 0 : v.trim() === "";
  if (empty) return f.required && !f.optional ? `${f.label} is required.` : null;
  const s = Array.isArray(v) ? "" : v.trim();
  const { min, max, pattern } = f.validation;
  if (f.component === "currency" || f.component === "number") {
    const n = Number(s.replace(/,/g, ""));
    if (Number.isNaN(n)) return `${f.label} must be a number.`;
    if (min != null && n < min) return `${f.label} must be at least ${min}.`;
    if (max != null && n > max) return `${f.label} must be at most ${max}.`;
  }
  if (f.component === "phone" && pattern && !new RegExp(pattern).test(s.replace(/[\s-]/g, ""))) return `${f.label} must be 10 digits.`;
  if (f.component === "date" && Number.isNaN(Date.parse(s))) return `${f.label} is not a valid date.`;
  if (f.component === "select" && f.validation.options.length && !f.validation.options.includes(s)) return `Choose one of the listed options.`;
  return null;
}

export function initialValue(f: FieldComponent): Raw {
  const v = f.value;
  if (v === null || v === undefined) return f.component === "multi_select" ? [] : "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map(String);
  return String(v);
}

const INPUT = "w-full border bg-sheet px-3 py-2 outline-none focus:border-cobalt";

interface Props {
  field: FieldComponent;
  value: Raw;
  onChange: (v: Raw) => void;
  error?: string | null;
  confirmed?: boolean;
  onConfirm?: (b: boolean) => void;
  disabled?: boolean;
}

export function FieldInput({ field: f, value, onChange, error, confirmed, onConfirm, disabled }: Props) {
  const id = useId();
  const baseId = `field-${f.field_id}`;
  const describedBy = [f.help && `${id}-help`, error && `${id}-err`, f.provenance.quote && `${id}-prov`].filter(Boolean).join(" ") || undefined;
  const border = error ? "border-danger" : "border-rule";
  const str = Array.isArray(value) ? "" : value;
  const common = { id: baseId, disabled, "aria-describedby": describedBy, "aria-invalid": !!error || undefined, "aria-required": (f.required && !f.optional) || undefined };
  const low = f.provenance.confidence != null && f.provenance.confidence < 0.7 && f.provenance.status === "suggested";

  let control: React.ReactNode;
  switch (f.component) {
    case "long_text":
      control = <textarea {...common} rows={4} value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} resize-y`} />;
      break;
    case "address":
      control = <textarea {...common} rows={2} autoComplete="street-address" value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} resize-y`} />;
      break;
    case "currency":
      control = (
        <div className={`flex items-center border bg-sheet focus-within:border-cobalt ${border}`}>
          <span className="pl-3 text-muted" aria-hidden>Rs.</span>
          <input {...common} inputMode="decimal" value={str} onChange={(e) => onChange(e.target.value)} className="w-full bg-transparent px-2 py-2 outline-none tabular-nums" />
        </div>
      );
      break;
    case "number":
      control = <input {...common} type="number" inputMode="numeric" min={f.validation.min ?? undefined} max={f.validation.max ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} tabular-nums sm:max-w-[10rem]`} />;
      break;
    case "phone":
      control = <input {...common} type="tel" inputMode="numeric" autoComplete="tel-national" value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} tabular-nums sm:max-w-[16rem]`} />;
      break;
    case "date":
      control = <input {...common} type="date" value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} sm:max-w-[14rem]`} />;
      break;
    case "select":
      control = (
        <select {...common} value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border} sm:max-w-[22rem]`}>
          <option value="">Choose…</option>
          {f.validation.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
      break;
    case "multi_select": {
      const set = new Set(Array.isArray(value) ? value : []);
      control = (
        <div role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap gap-x-5 gap-y-1">
          {f.validation.options.map((o) => (
            <label key={o} className="flex items-center gap-2">
              <input type="checkbox" checked={set.has(o)} disabled={disabled} className="h-4 w-4 accent-cobalt"
                onChange={(e) => { const next = new Set(set); e.target.checked ? next.add(o) : next.delete(o); onChange([...next]); }} />
              {o}
            </label>
          ))}
        </div>
      );
      break;
    }
    case "yes_no":
      control = (
        <div role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={describedBy} className="inline-flex border border-ink">
          {(["yes", "no"] as const).map((o) => (
            <label key={o} className={`cursor-pointer px-5 py-2 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-cobalt ${str === o ? "bg-ink text-sheet" : "hover:bg-rule-soft"}`}>
              <input type="radio" name={baseId} value={o} checked={str === o} disabled={disabled} onChange={() => onChange(o)} className="sr-only" />
              {o === "yes" ? "Yes" : "No"}
            </label>
          ))}
        </div>
      );
      break;
    case "party_select":
      control = f.party_options.length === 0 ? (
        <p className="text-muted">No saved records of this kind exist for your business yet.</p>
      ) : (
        <div role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={describedBy} className="grid gap-2 sm:grid-cols-2">
          {f.party_options.map((o) => (
            <label key={o.id} className={`flex cursor-pointer gap-3 border px-3 py-2.5 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-cobalt ${str === o.id ? "border-cobalt bg-cobalt-soft" : "border-rule bg-sheet hover:border-ink"}`}>
              <input type="radio" name={baseId} value={o.id} checked={str === o.id} disabled={disabled} onChange={() => onChange(o.id)} className="mt-1 h-4 w-4 accent-cobalt" />
              <span><span className="block font-medium">{o.label}</span>{o.detail && <span className="block text-[0.875rem] text-muted">{o.detail}</span>}</span>
            </label>
          ))}
        </div>
      );
      break;
    default:
      control = <input {...common} type="text" autoComplete={f.component === "person" ? "name" : "off"} value={str} onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${border}`} />;
  }

  const grouped = ["yes_no", "party_select", "multi_select"].includes(f.component);
  const prov = f.provenance;
  return (
    <div className="space-y-1.5">
      {grouped ? (
        <p id={`${id}-label`} className="font-medium">{f.label}{f.required && !f.optional && <span aria-hidden className="text-danger"> *</span>}</p>
      ) : (
        <label htmlFor={baseId} id={`${id}-label`} className="block font-medium">
          {f.label}{f.required && !f.optional && <span aria-hidden className="text-danger"> *</span>}
        </label>
      )}
      {control}
      {f.help && <p id={`${id}-help`} className="text-[0.875rem] text-muted">{f.help}</p>}
      {prov.quote && prov.status !== "none" && prov.status !== "default" && (
        <p id={`${id}-prov`} className="text-[0.875rem] text-ink-2">
          {prov.status === "confirmed" ? "You confirmed this. " : "Heard: "}
          <q className="font-display italic">{prov.quote}</q>
          {low && <span className="ml-2 font-medium text-ochre">Check this one.</span>}
        </p>
      )}
      {prov.status === "default" && <p className="text-[0.875rem] text-muted">Template default ({prov.origin}). Change it if the agreement differs.</p>}
      {f.needs_confirmation && onConfirm && (
        <label className="flex items-center gap-2 text-[0.9375rem]">
          <input type="checkbox" checked={!!confirmed} onChange={(e) => onConfirm(e.target.checked)} className="h-4 w-4 accent-cobalt" />
          This is correct
        </label>
      )}
      {error && <p id={`${id}-err`} role="alert" className="text-[0.875rem] font-medium text-danger">{error}</p>}
    </div>
  );
}
