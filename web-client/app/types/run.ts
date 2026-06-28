import type { BlockType, RunStatus } from "./common";

export interface BlockRunDTO {
  id: number;
  run_id: number;
  type: BlockType;
  position: number;
  config: Record<string, unknown>;
  status: RunStatus;
  artifact_ref: string | null;
  metrics: Record<string, unknown> | null;
  error: string | null;
}

export interface PipelineRunDTO {
  id: number;
  pipeline_id: number;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  blocks: BlockRunDTO[];
}
