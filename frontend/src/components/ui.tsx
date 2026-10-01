import { AlertTriangle, Inbox, Loader2, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import type { DataClass } from "../types/api";

export function Panel({ title, right, children, className = "", bodyClass = "" }: {
  title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`panel flex flex-col min-h-0 ${className}`} aria-label={typeof title === "string" ? title : undefined}>
      <header className="panel-title shrink-0">
        <h2 className="m-0 font-medium text-2xs">{title}</h2>
        {right && <div className="flex items-center gap-2 normal-case tracking-normal">{right}</div>}
      </header>
      <div className={`min-h-0 overflow-auto ${bodyClass || "p-3"}`}>{children}</div>
    </section>
  );
}

export function KV({ k, v, title }: { k: string; v: ReactNode; title?: string }) {
  return (
    <div className="kv" title={title}>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-dim py-3">
      <Loader2 size={13} className="animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col gap-2 text-xs py-2">
      <div className="flex items-start gap-2 text-crit">
        <AlertTriangle size={13} className="mt-[2px] shrink-0" aria-hidden />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button className="btn self-start h-7" onClick={onRetry}>
          <RotateCw size={12} aria-hidden /> Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-dim py-2">
      <Inbox size={13} className="mt-[2px] shrink-0" aria-hidden />
      <div>
        <div>{message}</div>
        {hint && <div className="text-2xs mt-1 text-dim/80">{hint}</div>}
      </div>
    </div>
  );
}

const DC_STYLE: Record<DataClass, string> = {
  observed: "border-info/50 text-info",
  simulated: "border-warn/50 text-warn",
  predicted: "border-fire/60 text-fire",
  validated: "border-ok/50 text-ok",
};

/** Data-provenance tag: text label, never colour alone. */
export function DataClassTag({ c }: { c: DataClass }) {
  return <span className={`tag ${DC_STYLE[c]}`}>{c}</span>;
}

const SEV_STYLE: Record<string, string> = {
  INFO: "border-info/50 text-info",
  WARNING: "border-warn/60 text-warn",
  HIGH: "border-crit/60 text-crit",
  CRITICAL: "border-crit text-crit bg-crit/10",
};

export function SeverityTag({ s }: { s: string }) {
  return <span className={`tag ${SEV_STYLE[s] ?? "border-line text-dim"}`}>{s}</span>;
}

export function StatusDot({ state, label }: { state: "ok" | "warn" | "crit" | "off"; label: string }) {
  const c = { ok: "bg-ok", warn: "bg-warn", crit: "bg-crit", off: "bg-dim" }[state];
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs uppercase tracking-wider">
      <span className={`inline-block w-1.5 h-1.5 ${c}`} aria-hidden />
      {label}
    </span>
  );
}
