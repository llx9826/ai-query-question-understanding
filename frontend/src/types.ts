export interface WrenSource {
  model: string; dataset_id?: string | null; source_name?: string | null;
  content_hash?: string | null; sheet?: string | null; description?: string | null;
}
export interface WrenResult {
  workspace_id: string; publication_id: string; request_id: string; trace_id: string;
  status: 'answered' | 'needs_clarification' | 'unsupported'; answer: string;
  logical_sql?: string | null; dialect_sql?: string | null; columns: string[];
  rows: Record<string, unknown>[]; truncated: boolean; sources: WrenSource[];
  model_name: string; model_calls: number;
}
export interface Reply {
  trace_id: string; turn_id: string; workspace_id: string;
  publication_id?: string | null; context_saved: boolean;
  result?: WrenResult | null;
  failure?: { message: string; code: string; module: string; node: string } | null;
}
export interface ChatMessage {
  id: string; role: string; text: string; reply?: Reply | null; finished_reason?: string;
}
export interface Session { id: string; name: string; updated_at: string; is_running: boolean; workspace_id: string }
export interface Stage { module: string; stage: string; status: string; duration_ms?: number }
export interface Snapshot {
  messages: ChatMessage[]; is_running: boolean; has_more: boolean;
  progress?: { trace_id: string; status: string; duration_ms?: number; stages: Stage[]; model_calls: number };
  active_publication_id?: string | null;
}
export interface Workspace {
  agent_id: string; workspace_id: string; source_name: string; source_id: string;
  workspaces: { workspace_id: string; name: string }[];
  wren_configured: boolean;
}
export interface DatasetTable {
  sheet: string; model: string; table: string; row_count: number;
  columns: { name: string; type: string }[];
}
export interface DatasetSummary {
  dataset_id: string; source_name: string; content_hash: string; tables: DatasetTable[];
}
export interface RelationshipDefinition {
  name: string; models: [string, string];
  join_type: 'ONE_TO_ONE' | 'ONE_TO_MANY' | 'MANY_TO_ONE' | 'MANY_TO_MANY';
  condition: string;
}
export interface PublicationResult {
  workspace_id: string; publication_id: string; changed: boolean; datasets: DatasetSummary[];
  relationships?: RelationshipDefinition[];
}
export interface PublicationSummary {
  publication_id: string; created_at: string; active: boolean; datasets: DatasetSummary[];
  relationships?: RelationshipDefinition[];
}
