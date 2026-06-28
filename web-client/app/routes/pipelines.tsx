import { Fragment, useEffect, useState } from "react";

import { AppendBlock } from "~/components/append-block";
import { CreatePipelineDialog } from "~/components/create-pipeline-dialog";
import { icons } from "~/components/icons";
import { RunsPanel } from "~/components/runs-panel";
import { Button } from "~/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { ScrollArea } from "~/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Skeleton } from "~/components/ui/skeleton";
import { useSchemes } from "~/hooks/schemes";
import {
  usePipeline,
  usePipelines,
  useStartRun,
} from "~/hooks/pipelines";
import type { Route } from "./+types/pipelines";

export default function Pipelines({ params }: Route.ComponentProps) {
  const datasetId = Number(params.datasetId);
  const pipelines = usePipelines(datasetId);
  const schemes = useSchemes(datasetId);
  const [creating, setCreating] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);

  useEffect(() => {
    if (activeId === null && pipelines.data?.length) {
      setActiveId(pipelines.data[0].id);
    }
  }, [activeId, pipelines.data]);

  if (pipelines.isPending) return <Skeleton className="m-4 h-96" />;

  if (!schemes.data?.length) {
    return (
      <Empty className="mt-16">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <icons.pipeline />
          </EmptyMedia>
          <EmptyTitle>Create a scheme first</EmptyTitle>
          <EmptyDescription>
            A pipeline trains on the labels of a scheme.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!pipelines.data?.length) {
    return (
      <>
        <Empty className="mt-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <icons.pipeline />
            </EmptyMedia>
            <EmptyTitle>No pipelines</EmptyTitle>
            <EmptyDescription>
              Compose blocks to vectorize, train, and evaluate.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <icons.add /> New pipeline
            </Button>
          </EmptyContent>
        </Empty>
        <CreatePipelineDialog
          datasetId={datasetId}
          open={creating}
          onOpenChange={setCreating}
          onCreated={setActiveId}
        />
      </>
    );
  }

  return (
    <>
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Select
          value={activeId ? String(activeId) : undefined}
          onValueChange={(v) => setActiveId(Number(v))}
        >
          <SelectTrigger size="sm" className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {pipelines.data.map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setCreating(true)}
        >
          <icons.add /> New
        </Button>
      </div>

      <ScrollArea className="flex-1">
        {activeId ? <PipelineBuilder pipelineId={activeId} /> : null}
      </ScrollArea>

      <CreatePipelineDialog
        datasetId={datasetId}
        open={creating}
        onOpenChange={setCreating}
        onCreated={setActiveId}
      />
    </>
  );
}

function PipelineBuilder({ pipelineId }: { pipelineId: number }) {
  const pipeline = usePipeline(pipelineId);
  const startRun = useStartRun(pipelineId);

  if (!pipeline.data) return <Skeleton className="m-4 h-40" />;
  const blocks = [...pipeline.data.blocks].sort(
    (a, b) => a.position - b.position,
  );

  return (
    <div className="space-y-6 p-4">
      {/* Block chain */}
      <section className="space-y-2">
        <h3 className="text-muted-foreground text-xs font-medium uppercase">
          Blocks
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          {blocks.length ? (
            blocks.map((b, i) => (
              <Fragment key={b.id}>
                {i > 0 ? (
                  <icons.next className="text-muted-foreground size-4 shrink-0" />
                ) : null}
                <div className="bg-card flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
                  <icons.block className="text-muted-foreground size-4" />
                  {b.type}
                </div>
              </Fragment>
            ))
          ) : (
            <p className="text-muted-foreground text-sm">
              Empty — start with a clean or vectorize block.
            </p>
          )}
        </div>
        <div className="pt-1">
          <AppendBlock pipelineId={pipelineId} />
        </div>
      </section>

      {/* Runs */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-muted-foreground text-xs font-medium uppercase">
            Runs
          </h3>
          <Button
            size="sm"
            onClick={() => startRun.mutate()}
            disabled={!blocks.length || startRun.isPending}
          >
            <icons.run /> Run pipeline
          </Button>
        </div>
        <RunsPanel pipelineId={pipelineId} />
      </section>
    </div>
  );
}
