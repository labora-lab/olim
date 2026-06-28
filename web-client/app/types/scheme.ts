import type { FieldType } from "./common";

export interface OptionDTO {
  id: number;
  field_id: number;
  name: string;
}

export interface FieldDTO {
  id: number;
  scheme_id: number;
  name: string;
  type: FieldType;
  min: number | null;
  max: number | null;
  step: number | null;
  multi: boolean;
  allow_other: boolean;
  nullable: boolean;
  options: OptionDTO[];
}

export interface SchemeDTO {
  id: number;
  dataset_id: number;
  name: string;
  fields: FieldDTO[];
}

export interface OptionIn {
  name: string;
}

export interface SelectFieldIn {
  type: "select";
  name: string;
  multi?: boolean;
  allow_other?: boolean;
  options?: OptionIn[];
}

export interface NumericFieldIn {
  type: "numeric";
  name: string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
}

export interface TextFieldIn {
  type: "text";
  name: string;
}

export interface BooleanFieldIn {
  type: "boolean";
  name: string;
  nullable?: boolean;
}

export type FieldIn =
  | SelectFieldIn
  | NumericFieldIn
  | TextFieldIn
  | BooleanFieldIn;

export interface SchemeCreateIn {
  name: string;
  fields?: FieldIn[];
}
