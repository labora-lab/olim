import { http } from "~/lib/http";
import type { ItemDTO, ItemUpload } from "~/types/item";

export const itemsService = {
  list: (datasetId: number) =>
    http.get<ItemDTO[]>("/items", { dataset_id: datasetId }),
  upload: (datasetId: number, body: ItemUpload) =>
    http.post<ItemDTO[]>("/items", body, { dataset_id: datasetId }),
};
