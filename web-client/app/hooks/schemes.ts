import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { schemesService } from "~/services/schemes";
import type { SchemeCreateIn } from "~/types/scheme";

export const schemeKeys = {
  list: (datasetId: number) => ["schemes", { datasetId }] as const,
};

export function useSchemes(datasetId: number) {
  return useQuery({
    queryKey: schemeKeys.list(datasetId),
    queryFn: () => schemesService.list(datasetId),
  });
}

export function useCreateScheme(datasetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SchemeCreateIn) =>
      schemesService.create(datasetId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: schemeKeys.list(datasetId) }),
  });
}
