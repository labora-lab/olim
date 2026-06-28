import { icons } from "~/components/icons";
import { RunStatusBadge } from "~/components/run-status-badge";
import { useRun } from "~/hooks/runs";
import { usePipelineRuns } from "~/hooks/pipelines";

export function RunsPanel({ pipelineId }: { pipelineId: number }) {
  const runs = usePipelineRuns(pipelineId);

  if (!runs.data?.length) {
    return <p className="text-muted-foreground text-sm">No runs yet.</p>;
  }

  return (
    <div className="space-y-2">
      {runs.data.map((r) => (
        <RunRow key={r.id} runId={r.id} />
      ))}
    </div>
  );
}

// Subscribes per-run so an in-progress run polls itself (see useRun).
function RunRow({ runId }: { runId: number }) {
  const run = useRun(runId);
  if (!run.data) return null;

  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-2 px-3 py-2">
        <icons.run className="text-muted-foreground size-4" />
        <span className="text-sm font-medium">Run #{run.data.id}</span>
        <span className="ml-auto">
          <RunStatusBadge status={run.data.status} />
        </span>
      </div>
      <div className="divide-y border-t">
        {run.data.blocks.map((b) => (
          <div key={b.id} className="flex items-center gap-2 px-3 py-1.5">
            <span className="text-muted-foreground w-5 text-xs tabular-nums">
              {b.position}
            </span>
            <span className="text-sm">{b.type}</span>
            <span className="ml-auto">
              <RunStatusBadge status={b.status} />
            </span>
            {b.metrics ? (
              <span className="text-muted-foreground font-mono text-xs">
                {Object.entries(b.metrics)
                  .map(
                    ([k, v]) =>
                      `${k} ${typeof v === "number" ? v.toFixed(3) : v}`,
                  )
                  .join("  ")}
              </span>
            ) : null}
            {b.error ? (
              <span className="text-destructive text-xs">{b.error}</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
