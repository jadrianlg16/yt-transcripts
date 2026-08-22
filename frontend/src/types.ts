/** Shapes returned by the backend API, shared across the app. */

export interface Segment {
  text: string;
  start: number;
  duration: number;
}

export interface Transcript {
  video_id: string;
  title: string;
  channel: string;
  saved_at: string;
  uploaded_at?: string;
  fetched_at?: string;
  source_url?: string;
  /** Absent on list rows from /api/transcripts; present on a fetched detail. */
  transcript?: string;
  segments?: Segment[];
  /** Precomputed on list rows so the list never needs the segments. */
  transcript_char_count?: number;
  segment_count?: number;
  duration_seconds?: number;
}

export interface TaskStatus {
  run_id?: string | null;
  current_task: string | null;
  progress: number;
  total: number;
  message: string;
  success_count?: number;
  failure_count?: number;
  skipped_count?: number;
  recent_events?: { time: string; message: string; progress: number; total: number }[];
}

export interface LibraryStats {
  transcript_count: number;
  unique_channels: number;
  total_words: number;
  total_segments: number;
  total_duration_seconds: number;
  latest_saved_at: string;
  channel_counts: { channel: string; count: number }[];
  top_keywords: { term: string; count: number }[];
}

export interface SearchMatch {
  text: string;
  start: number;
  duration: number;
}

export interface SearchResult {
  video_id: string;
  title: string;
  channel: string;
  saved_at: string;
  uploaded_at?: string;
  score: number;
  matches: SearchMatch[];
  word_count?: number;
  runtime_seconds?: number;
  duration_seconds?: number;
  segment_count?: number;
  match_count?: number;
}

export interface StorageStatus {
  backend: 'json' | 'sqlite';
  active_count: number;
  json: {
    path: string;
    exists: boolean;
    count: number;
  };
  sqlite: {
    path: string;
    exists: boolean;
    count: number;
    fts_enabled: boolean;
  };
}

export interface MCPStatus {
  enabled: boolean;
  read_only: boolean;
  server_name: string;
  tools: string[];
  storage_backend: string;
  config: {
    path: string;
    exists: boolean;
  };
  settings?: {
    updated_at?: string | null;
  };
}

export interface SystemStatus {
  settings: {
    ingestion_paused: boolean;
    maintenance_mode: boolean;
    updated_at?: string | null;
  };
  backend: {
    online: boolean;
    restart_supported: boolean;
    shutdown_supported: boolean;
    message?: string;
  };
  watcher: {
    thread_alive: boolean;
    stop_requested: boolean;
  };
}

export interface DataTableSummary {
  name: string;
  count: number;
  columns: string[];
}

export interface DataTableResponse {
  name: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

export interface TimestampNote {
  id: string;
  video_id: string;
  start: number;
  text: string;
  created_at: string;
  updated_at: string;
}

export interface CollectionClip {
  id: string;
  video_id: string;
  start: number;
  end: number | null;
  text: string;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface ResearchCollection {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  clips: CollectionClip[];
}

export interface ResearchOrganization {
  tags: Record<string, string[]>;
  video_notes: Record<string, string>;
  timestamp_notes: Record<string, TimestampNote[]>;
  collections: ResearchCollection[];
}

export interface BackendEvent {
  id: number;
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error';
  event: string;
  message: string;
  details: Record<string, unknown>;
}

export interface FetchRunItem {
  video_id?: string | null;
  title?: string;
  url?: string | null;
  error?: string;
  reason?: string;
  index?: number | null;
  total?: number | null;
  failed_at?: string;
  saved_at?: string;
  skipped_at?: string;
  retryable?: boolean;
}

export interface FetchRun {
  id: string;
  type: string;
  source: string;
  status: string;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
  message: string;
  total: number;
  success_count: number;
  failure_count: number;
  skipped_count: number;
  successes: FetchRunItem[];
  failures: FetchRunItem[];
  skipped: FetchRunItem[];
  metadata?: Record<string, unknown>;
}

export interface ChannelCandidate {
  video_id: string;
  title: string;
  url: string;
  published_text: string;
  already_saved: boolean;
  selected: boolean;
}

export interface ChannelPreview {
  channel: string;
  listing_source: string;
  total: number;
  new_count: number;
  already_saved_count: number;
  candidates: ChannelCandidate[];
}

export interface WatcherSettings {
  enabled: boolean;
  channels: string[];
  frequency_minutes: number;
  languages: string[];
  last_checked_at?: string | null;
  next_check_at?: string | null;
}

export interface AISettings {
  enabled: boolean;
  provider: string;
  base_url: string;
  summary_model: string;
  embedding_model: string;
  timeout_seconds: number;
  temperature: number;
  prompt_version?: string;
}

export interface AISettingsDraft {
  enabled: boolean;
  provider: string;
  baseUrl: string;
  summaryModel: string;
  embeddingModel: string;
  timeoutSeconds: string;
  temperature: string;
}

export interface AIModelOptions {
  all: string[];
  summary: string[];
  embedding: string[];
  provider?: string;
}

export interface AIHealthResult {
  ok?: boolean;
  success?: boolean;
  status?: string;
  message?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
}

export interface AIArtifact {
  id?: string;
  video_id?: string;
  video_ids?: string[];
  type?: string;
  kind?: string;
  status?: string;
  provider?: string;
  model?: string;
  prompt_version?: string;
  generated_at?: string;
  created_at?: string;
  title?: string;
  stale?: boolean;
  error?: string;
  content?: unknown;
}

export interface AITranscriptSummary {
  video_id: string;
  text: string;
  key_claims: string[];
  entities: string[];
  suggested_tags: string[];
  warnings: string[];
  provider?: string;
  model?: string;
  prompt_version?: string;
  generated_at?: string;
  status?: string;
  stale?: boolean;
  artifact_id?: string;
}

export interface SemanticSearchResult extends SearchResult {
  semantic_score?: number;
  similarity?: number;
  excerpt?: string;
  reason?: string;
}

export interface EmbeddingStatus {
  exists: boolean;
  path?: string;
  embedding_model?: string;
  chunk_count: number;
  stale_count: number;
  stale_video_ids: string[];
}

export type LogType = 'info' | 'warning' | 'error' | 'success';
export type ActiveView = 'library' | 'settings';
export type SettingsSection = 'automation' | 'ai' | 'mcp' | 'data' | 'system';
export type SortOption = 'relevance' | 'newest' | 'longest' | 'most_matches' | 'title';
export type DataExportScope = 'all' | 'channel' | 'selected' | 'collection' | 'search';
export type DataExportFormat = 'json' | 'jsonl' | 'csv' | 'markdown';

export interface LogEntry {
  id: string;
  msg: string;
  type: LogType;
  time: string;
  source: 'frontend' | 'backend';
  event?: string;
  details?: Record<string, unknown>;
}

export interface ArchivedVideo {
  video_id: string;
  title: string;
  channel: string;
  filename: string;
  size_bytes: number;
  archived_at: number;
  has_transcript: boolean;
}

export interface ArchiveStorage {
  path: string;
  exists: boolean;
  count: number;
  used_bytes: number;
  free_bytes: number | null;
  available: boolean;
}
