import { utc } from "../lib/format";
import { useApp } from "../stores/app";
import { EmptyState, Panel, SeverityTag } from "./ui";

export default function AlertPanel({ fireId, limit = 6, className = "" }: { fireId?: string | null; limit?: number; className?: string }) {
  const all = useApp((s) => s.alerts);
  const alerts = (fireId ? all.filter((a) => a.fire_id === fireId || a.fire_id === null) : all).slice(0, limit);
  return (
    <Panel title="Change Status / Alerts" className={className}>
      {alerts.length === 0 ? (
        <EmptyState message="No alerts." hint="Alerts are raised only when configured thresholds are exceeded." />
      ) : (
        <ul className="m-0 p-0 list-none space-y-2">
          {alerts.map((a) => (
            <li key={a.alert_id} className="border border-line p-2">
              <div className="flex items-center gap-2 mb-1">
                <SeverityTag s={a.severity} />
                <span className="text-xs text-head">[ {a.title} ]</span>
                <span className="ml-auto text-2xs text-dim">{utc(a.created_at)}</span>
              </div>
              {a.fire_id && <div className="text-2xs text-dim mb-1">{a.fire_id}</div>}
              <ul className="m-0 p-0 list-none text-xs">
                {a.lines.map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
