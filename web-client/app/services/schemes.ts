import { http } from "~/lib/http";
import type { SchemeCreateIn, SchemeDTO } from "~/types/scheme";

export const schemesService = {
  list: (datasetId: number) =>
    http.get<SchemeDTO[]>("/schemes", { dataset_id: datasetId }),
  create: (datasetId: number, body: SchemeCreateIn) =>
    http.post<SchemeDTO>("/schemes", body, { dataset_id: datasetId }),
};
