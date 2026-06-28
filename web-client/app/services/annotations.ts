import { http } from "~/lib/http";
import type { AnnotateIn, AnnotationDTO } from "~/types/annotation";

export const annotationsService = {
  list: (itemId: number) =>
    http.get<AnnotationDTO[]>("/annotations", { item_id: itemId }),
  annotate: (itemId: number, body: AnnotateIn) =>
    http.post<AnnotationDTO[]>("/annotations", body, { item_id: itemId }),
};
