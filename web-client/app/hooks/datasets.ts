import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { datasetsService } from "~/services/datasets";
import type { DatasetCreate } from "~/types/dataset";

export const datasetKeys = {
  all: ["datasets"] as const,
  detail: (id: number) => ["datasets", id] as const,
};

export function useDatasets() {
  return useQuery({
    queryKey: datasetKeys.all,
    queryFn: datasetsService.list,
  });
}

export function useDataset(id: number) {
  return useQuery({
    queryKey: datasetKeys.detail(id),
    queryFn: () => datasetsService.get(id),
  });
}

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DatasetCreate) => datasetsService.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: datasetKeys.all }),
  });
}
