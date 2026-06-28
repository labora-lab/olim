import type { AnnotationSource } from "./common";

export type AnnotationValue = number | string | boolean | null;

export interface AnnotationDTO {
  id: number;
  item_id: number;
  field_id: number;
  source: AnnotationSource;
  value: AnnotationValue;
}

export interface AnswerIn {
  field_id: number;
  value?: unknown;
}

export interface AnnotateIn {
  answers: AnswerIn[];
}
