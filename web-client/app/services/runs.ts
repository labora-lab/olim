import { http } from "~/lib/http";
import type { PipelineRunDTO } from "~/types/run";

export const runsService = {
  get: (id: number) => http.get<PipelineRunDTO>(`/runs/${id}`),
};
