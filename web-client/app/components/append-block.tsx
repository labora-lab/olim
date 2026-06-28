import { useState } from "react";

import { BlockConfigForm, useBlockConfig } from "~/components/block-config-form";
import { icons } from "~/components/icons";
import { Button } from "~/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { useAppendBlock, usePipelineCandidates } from "~/hooks/pipelines";
import type { BlockIn } from "~/types/pipeline";

// The "what fits next" engine: only valid candidates are offered. Picking one
// reveals its config (defaults from the schema) before appending.
export function AppendBlock({ pipelineId }: { pipelineId: number }) {
  const candidates = usePipelineCandidates(pipelineId);
  const [picked, setPicked] = useState<
    NonNullable<typeof candidates.data>[number] | null
  >(null);

  if (!candidates.data?.length) {
    return (
      <p className="text-muted-foreground text-xs">
        No more blocks fit here.
      </p>
    );
  }

  if (!picked) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <icons.add /> Add block
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          {candidates.data.map((c) => (
            <DropdownMenuItem key={c.type} onSelect={() => setPicked(c)}>
              <icons.block className="text-muted-foreground" />
              <div className="flex flex-col">
                <span>{c.type}</span>
                <span className="text-muted-foreground text-xs">
                  {c.category}
                </span>
              </div>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  return <PickedConfig candidate={picked} pipelineId={pipelineId} onClose={() => setPicked(null)} />;
}

function PickedConfig({
  candidate,
  pipelineId,
  onClose,
}: {
  candidate: NonNullable<ReturnType<typeof usePipelineCandidates>["data"]>[number];
  pipelineId: number;
  onClose: () => void;
}) {
  const config = useBlockConfig(candidate.config_schema);
  const append = useAppendBlock(pipelineId);

  function add() {
    append.mutate(
      { type: candidate.type, ...config.values } as BlockIn,
      { onSuccess: onClose },
    );
  }

  return (
    <div className="bg-card flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <icons.block className="text-muted-foreground size-4" />
        <span className="text-sm font-medium">{candidate.type}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          onClick={onClose}
          aria-label="Cancel"
        >
          <icons.close />
        </Button>
      </div>
      <BlockConfigForm config={config} />
      <Button size="sm" onClick={add} disabled={append.isPending}>
        Append block
      </Button>
    </div>
  );
}
