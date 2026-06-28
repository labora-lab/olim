import type { DataType } from "./common";

export interface DatasetDTO {
  id: number;
  name: string;
  data_type: DataType;
}

export interface DatasetCreate {
  name: string;
  data_type?: DataType;
}
