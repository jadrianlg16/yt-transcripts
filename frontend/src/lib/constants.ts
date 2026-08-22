/** API base, storage keys, and the empty defaults state starts from. */

import type {
  AIModelOptions,
  AISettings,
  MCPStatus,
  ResearchOrganization,
  SystemStatus,
  WatcherSettings,
} from '../types';

export const API_BASE = import.meta.env.VITE_API_BASE || '/api';
export const SAVED_SEARCHES_KEY = 'yt-transcripts.saved-searches';

export const emptyResearchOrganization: ResearchOrganization = {
  tags: {},
  video_notes: {},
  timestamp_notes: {},
  collections: [],
};

export const emptyWatcherSettings: WatcherSettings = {
  enabled: false,
  channels: [],
  frequency_minutes: 360,
  languages: ['en'],
  last_checked_at: null,
  next_check_at: null,
};

export const emptyAISettings: AISettings = {
  enabled: false,
  provider: '',
  base_url: '',
  summary_model: '',
  embedding_model: '',
  timeout_seconds: 60,
  temperature: 0.2,
};

export const emptyAIModels: AIModelOptions = {
  all: [],
  summary: [],
  embedding: [],
};

export const emptyMCPStatus: MCPStatus = {
  enabled: true,
  read_only: true,
  server_name: 'yt-transcripts-readonly',
  tools: [],
  storage_backend: 'unknown',
  config: {
    path: '',
    exists: false,
  },
};

export const emptySystemStatus: SystemStatus = {
  settings: {
    ingestion_paused: false,
    maintenance_mode: false,
  },
  backend: {
    online: false,
    restart_supported: false,
    shutdown_supported: false,
  },
  watcher: {
    thread_alive: false,
    stop_requested: false,
  },
};
