import { clock } from "../lib/format";
import { useApp } from "../stores/app";
import { EmptyState, Panel, StatusDot } from "./ui";

const LEVEL_CLASS: Record<string, string> = { ERROR: "text-crit", WARNING: "text-warn", INFO: "text-ink" };

export default function SystemLogPanel({ limit = 60, className = "" }: { limit?: number; className?: string }) {
  const logs = useApp((s) => s.logs);
  const live = useApp((s) => s.live);
  return (
    <Panel title="System Logs" className={className} bodyClass="p-0" right={<StatusDot state={live ? "ok" : "warn"} label={live ? "stream" : "polling off"} />}>
      {logs.length === 0 ? <div className="p-3"><EmptyState message="No events yet." /></div> : (
        <ol className="m-0 p-2 list-none text-2xs leading-[17px]" aria-live="polite">
          {logs.slice(0, limit).map((l, i) => (
            <li key={`${l.ts}-${i}`} className={`whitespace-pre-wrap ${LEVEL_CLASS[l.level] ?? "text-ink"}`}>
              <span className="text-dim">[{clock(l.ts)}]</span> <span className="text-dim">{l.component.padEnd(10, " ")}</span> {l.message}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
