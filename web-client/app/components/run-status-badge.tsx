import { icons } from "~/components/icons";
import { Badge } from "~/components/ui/badge";
import { cn } from "~/lib/utils";
import type { RunStatus } from "~/types/common";

const styles: Record<RunStatus, string> = {
  pending: "text-muted-foreground",
  running: "text-primary",
  succeeded: "text-green-600 dark:text-green-400",
  failed: "text-destructive",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const running = status === "running" || status === "pending";
  return (
    <Badge variant="outline" className={cn("gap-1", styles[status])}>
      {running ? (
        <icons.spinner className="size-3 animate-spin" />
      ) : status === "succeeded" ? (
        <icons.done className="size-3" />
      ) : (
        <icons.error className="size-3" />
      )}
      {status}
    </Badge>
  );
}
