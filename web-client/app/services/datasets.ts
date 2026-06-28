import { http } from "~/lib/http";
import type { DatasetCreate, DatasetDTO } from "~/types/dataset";

export const datasetsService = {
  list: () => http.get<DatasetDTO[]>("/datasets"),
  get: (id: number) => http.get<DatasetDTO>(`/datasets/${id}`),
  create: (body: DatasetCreate) => http.post<DatasetDTO>("/datasets", body),
};
