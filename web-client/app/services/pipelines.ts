import { http } from "~/lib/http";
import type {
  BlockIn,
  CandidateOut,
  PipelineCreateIn,
  PipelineDTO,
} from "~/types/pipeline";
import type { PipelineRunDTO } from "~/types/run";

export const pipelinesService = {
  list: (datasetId: number) =>
    http.get<PipelineDTO[]>("/pipelines", { dataset_id: datasetId }),
  get: (id: number) => http.get<PipelineDTO>(`/pipelines/${id}`),
  create: (datasetId: number, schemeId: number, body: PipelineCreateIn) =>
    http.post<PipelineDTO>("/pipelines", body, {
      dataset_id: datasetId,
      scheme_id: schemeId,
    }),
  candidates: (id: number) =>
    http.get<CandidateOut[]>(`/pipelines/${id}/candidates`),
  appendBlock: (id: number, body: BlockIn) =>
    http.post<PipelineDTO>(`/pipelines/${id}/blocks`, body),
  startRun: (id: number) =>
    http.post<PipelineRunDTO>(`/pipelines/${id}/runs`),
  listRuns: (id: number) =>
    http.get<PipelineRunDTO[]>(`/pipelines/${id}/runs`),
};
