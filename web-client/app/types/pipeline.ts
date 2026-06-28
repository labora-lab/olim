import type { BlockType } from "./common";

export interface PipelineBlockDTO {
  id: number;
  pipeline_id: number;
  type: BlockType;
  position: number;
  config: Record<string, unknown>;
}

export interface PipelineDTO {
  id: number;
  dataset_id: number;
  scheme_id: number;
  name: string;
  blocks: PipelineBlockDTO[];
}

export interface PipelineCreateIn {
  name: string;
}

export interface CandidateOut {
  type: BlockType;
  category: string;
  consumes: string[];
  produces: string[];
  config_schema: Record<string, unknown>;
}

// Block configs accepted by POST /pipelines/{id}/blocks (discriminated on `type`).
export interface LowercaseBlockIn {
  type: "lowercase";
}
export interface StripStopwordsBlockIn {
  type: "strip_stopwords";
}
export interface TfidfBlockIn {
  type: "tfidf";
  max_features?: number | null;
  ngram_max?: number;
}
export interface CountVectorizerBlockIn {
  type: "count_vectorizer";
  max_features?: number | null;
  ngram_max?: number;
}
export interface TrainTestSplitBlockIn {
  type: "train_test_split";
  test_size?: number;
}
export interface TrainCalibTestSplitBlockIn {
  type: "train_calib_test_split";
  test_size?: number;
  calib_size?: number;
}
export interface LogRegBlockIn {
  type: "logreg";
  C?: number;
}
export interface RandomForestBlockIn {
  type: "random_forest";
  n_estimators?: number;
}
export interface XGBoostBlockIn {
  type: "xgboost";
  n_estimators?: number;
  learning_rate?: number;
}
export interface ConformalBlockIn {
  type: "conformal";
  alpha?: number;
}
export interface ClassificationMetricsBlockIn {
  type: "classification_metrics";
}
export interface PickleArtifactBlockIn {
  type: "pickle_artifact";
}

export type BlockIn =
  | LowercaseBlockIn
  | StripStopwordsBlockIn
  | TfidfBlockIn
  | CountVectorizerBlockIn
  | TrainTestSplitBlockIn
  | TrainCalibTestSplitBlockIn
  | LogRegBlockIn
  | RandomForestBlockIn
  | XGBoostBlockIn
  | ConformalBlockIn
  | ClassificationMetricsBlockIn
  | PickleArtifactBlockIn;
