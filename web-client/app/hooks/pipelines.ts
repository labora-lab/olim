import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { pipelinesService } from "~/services/pipelines";
import type { BlockIn, PipelineCreateIn } from "~/types/pipeline";
import { runKeys } from "./runs";

export const pipelineKeys = {
  list: (datasetId: number) => ["pipelines", { datasetId }] as const,
  detail: (id: number) => ["pipelines", id] as const,
  candidates: (id: number) => ["pipelines", id, "candidates"] as const,
  runs: (id: number) => ["pipelines", id, "runs"] as const,
};

export function usePipelines(datasetId: number) {
  return useQuery({
    queryKey: pipelineKeys.list(datasetId),
    queryFn: () => pipelinesService.list(datasetId),
  });
}

export function usePipeline(id: number) {
  return useQuery({
    queryKey: pipelineKeys.detail(id),
    queryFn: () => pipelinesService.get(id),
  });
}

export function useCreatePipeline(datasetId: number, schemeId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PipelineCreateIn) =>
      pipelinesService.create(datasetId, schemeId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: pipelineKeys.list(datasetId) }),
  });
}

// Blocks that may be appended next, given the pipeline so far.
export function usePipelineCandidates(id: number) {
  return useQuery({
    queryKey: pipelineKeys.candidates(id),
    queryFn: () => pipelinesService.candidates(id),
  });
}

export function useAppendBlock(pipelineId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BlockIn) =>
      pipelinesService.appendBlock(pipelineId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pipelineKeys.detail(pipelineId) });
      qc.invalidateQueries({ queryKey: pipelineKeys.candidates(pipelineId) });
    },
  });
}

export function usePipelineRuns(id: number) {
  return useQuery({
    queryKey: pipelineKeys.runs(id),
    queryFn: () => pipelinesService.listRuns(id),
  });
}

export function useStartRun(pipelineId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => pipelinesService.startRun(pipelineId),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: pipelineKeys.runs(pipelineId) });
      qc.setQueryData(runKeys.detail(run.id), run);
    },
  });
}
