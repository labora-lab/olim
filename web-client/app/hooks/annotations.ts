import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { annotationsService } from "~/services/annotations";
import type { AnnotateIn } from "~/types/annotation";

export const annotationKeys = {
  list: (itemId: number) => ["annotations", { itemId }] as const,
};

export function useAnnotations(itemId: number) {
  return useQuery({
    queryKey: annotationKeys.list(itemId),
    queryFn: () => annotationsService.list(itemId),
  });
}

export function useAnnotate(itemId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AnnotateIn) => annotationsService.annotate(itemId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: annotationKeys.list(itemId) }),
  });
}
