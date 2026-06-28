export type DataType = "text";
export type FieldType = "select" | "numeric" | "text" | "boolean";
export type AnnotationSource = "human" | "llm";
export type RunStatus = "pending" | "running" | "succeeded" | "failed";

export type BlockType =
  | "lowercase"
  | "strip_stopwords"
  | "tfidf"
  | "count_vectorizer"
  | "train_test_split"
  | "train_calib_test_split"
  | "logreg"
  | "random_forest"
  | "xgboost"
  | "conformal"
  | "classification_metrics"
  | "pickle_artifact";

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}
