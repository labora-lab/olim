import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { itemsService } from "~/services/items";
import type { ItemUpload } from "~/types/item";

export const itemKeys = {
  list: (datasetId: number) => ["items", { datasetId }] as const,
};

export function useItems(datasetId: number) {
  return useQuery({
    queryKey: itemKeys.list(datasetId),
    queryFn: () => itemsService.list(datasetId),
  });
}

export function useUploadItems(datasetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ItemUpload) => itemsService.upload(datasetId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: itemKeys.list(datasetId) }),
  });
}
