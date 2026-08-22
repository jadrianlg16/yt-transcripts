/** Backend payloads are untrusted shapes; these turn them into known types. */

import { emptyAISettings, emptyMCPStatus } from './constants';
import type {
  AIArtifact,
  AIModelOptions,
  AISettings,
  AISettingsDraft,
  AITranscriptSummary,
  EmbeddingStatus,
  MCPStatus,
  SearchMatch,
  SearchResult,
  SemanticSearchResult,
  SystemStatus,
  Transcript,
} from '../types';

export const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

export const getStringValue = (record: Record<string, unknown>, key: string) => (
  typeof record[key] === 'string' ? record[key] as string : ''
);

export const getNumberValue = (record: Record<string, unknown>, key: string) => {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

export const getBooleanValue = (record: Record<string, unknown>, key: string, fallback = false) => {
  const value = record[key];
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') return ['1', 'true', 'yes', 'enabled'].includes(value.toLowerCase());
  return fallback;
};

export const getArrayValue = (record: Record<string, unknown>, key: string) => (
  Array.isArray(record[key]) ? record[key] as unknown[] : []
);

export const decodeDisplayText = (value: string | null | undefined) => {
  const text = String(value ?? '').replace(/\\u([0-9a-fA-F]{4})/g, (_match: string, hex: string) => (
    String.fromCharCode(Number.parseInt(hex, 16))
  ));

  if (typeof document === 'undefined') return text;

  const parser = document.createElement('textarea');
  parser.innerHTML = text;
  return parser.value;
};

export const normalizeTranscript = (transcript: Transcript): Transcript => ({
  ...transcript,
  title: decodeDisplayText(transcript.title),
  channel: decodeDisplayText(transcript.channel),
});

export const normalizeSearchResult = (result: SearchResult): SearchResult => ({
  ...result,
  title: decodeDisplayText(result.title),
  channel: decodeDisplayText(result.channel),
});

export const createAISettingsDraft = (settings: AISettings): AISettingsDraft => ({
  enabled: settings.enabled,
  provider: settings.provider,
  baseUrl: settings.base_url,
  summaryModel: settings.summary_model,
  embeddingModel: settings.embedding_model,
  timeoutSeconds: String(settings.timeout_seconds),
  temperature: String(settings.temperature),
});

export const parseStringList = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map(item => {
        if (typeof item === 'string') return item;
        if (isRecord(item)) return getStringValue(item, 'name') || getStringValue(item, 'model') || getStringValue(item, 'id') || getStringValue(item, 'text');
        return '';
      })
      .map(item => decodeDisplayText(item).trim())
      .filter(Boolean);
  }

  if (typeof value === 'string') {
    return value.split(/[,\n]/).map(item => decodeDisplayText(item).trim()).filter(Boolean);
  }

  return [];
};

export const uniqueStrings = (values: string[]) => (
  Array.from(new Set(values.map(value => value.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b))
);

export const normalizeAISettings = (data: unknown): AISettings => {
  if (!isRecord(data)) return emptyAISettings;

  return {
    enabled: getBooleanValue(data, 'enabled'),
    provider: getStringValue(data, 'provider'),
    base_url: getStringValue(data, 'base_url') || getStringValue(data, 'baseUrl'),
    summary_model: getStringValue(data, 'summary_model') || getStringValue(data, 'summaryModel'),
    embedding_model: getStringValue(data, 'embedding_model') || getStringValue(data, 'embeddingModel'),
    timeout_seconds: getNumberValue(data, 'timeout_seconds') ?? getNumberValue(data, 'timeout') ?? emptyAISettings.timeout_seconds,
    temperature: getNumberValue(data, 'temperature') ?? emptyAISettings.temperature,
    prompt_version: getStringValue(data, 'prompt_version') || undefined,
  };
};

export const normalizeAIModels = (data: unknown): AIModelOptions => {
  const record: Record<string, unknown> = isRecord(data) ? data : {};
  const allModels = uniqueStrings(parseStringList(isRecord(data) ? (record.models ?? data) : data));
  const summaryModels = uniqueStrings([
    ...parseStringList(record.summary_models),
    ...parseStringList(record.summary),
    ...parseStringList(record.chat_models),
    ...parseStringList(record.generation_models),
  ]);
  const embeddingModels = uniqueStrings([
    ...parseStringList(record.embedding_models),
    ...parseStringList(record.embeddings),
  ]);

  return {
    all: allModels,
    summary: summaryModels.length > 0 ? summaryModels : allModels,
    embedding: embeddingModels.length > 0 ? embeddingModels : allModels,
    provider: getStringValue(record, 'provider') || undefined,
  };
};

export const normalizeAIArtifacts = (data: unknown): AIArtifact[] => {
  const items = Array.isArray(data)
    ? data
    : isRecord(data)
      ? getArrayValue(data, 'artifacts')
      : [];

  return items.filter(isRecord).map(item => ({
    id: getStringValue(item, 'id') || getStringValue(item, 'artifact_id') || undefined,
    video_id: getStringValue(item, 'video_id') || undefined,
    type: getStringValue(item, 'type') || undefined,
    kind: getStringValue(item, 'kind') || undefined,
    status: getStringValue(item, 'status') || undefined,
    provider: getStringValue(item, 'provider') || undefined,
    model: getStringValue(item, 'model') || undefined,
    prompt_version: getStringValue(item, 'prompt_version') || undefined,
    generated_at: getStringValue(item, 'generated_at') || undefined,
    created_at: getStringValue(item, 'created_at') || undefined,
    title: decodeDisplayText(getStringValue(item, 'title')) || undefined,
    stale: getBooleanValue(item, 'stale'),
    error: getStringValue(item, 'error') || undefined,
    video_ids: parseStringList(item.video_ids),
    content: item.content,
  }));
};

export const normalizeAISummary = (data: unknown, videoId: string): AITranscriptSummary | null => {
  const payload = isRecord(data) && isRecord(data.summary) ? data.summary : data;
  if (!isRecord(payload)) return null;

  const text = getStringValue(payload, 'summary') ||
    getStringValue(payload, 'concise_summary') ||
    getStringValue(payload, 'text') ||
    getStringValue(payload, 'content');
  const keyClaims = parseStringList(payload.key_claims ?? payload.claims);
  const entities = parseStringList(payload.entities);
  const suggestedTags = parseStringList(payload.suggested_tags ?? payload.tags);
  const warnings = parseStringList(payload.warnings);

  if (!text && keyClaims.length === 0 && entities.length === 0 && suggestedTags.length === 0 && warnings.length === 0) {
    return null;
  }

  return {
    video_id: getStringValue(payload, 'video_id') || videoId,
    text: decodeDisplayText(text),
    key_claims: keyClaims,
    entities,
    suggested_tags: suggestedTags,
    warnings,
    provider: getStringValue(payload, 'provider') || undefined,
    model: getStringValue(payload, 'model') || undefined,
    prompt_version: getStringValue(payload, 'prompt_version') || undefined,
    generated_at: getStringValue(payload, 'generated_at') || getStringValue(payload, 'created_at') || undefined,
    status: getStringValue(payload, 'status') || undefined,
    stale: getBooleanValue(payload, 'stale'),
    artifact_id: getStringValue(payload, 'artifact_id') || getStringValue(payload, 'id') || undefined,
  };
};

export const normalizeSearchMatches = (value: unknown): SearchMatch[] => (
  Array.isArray(value)
    ? value.filter(isRecord).map(match => ({
      text: decodeDisplayText(getStringValue(match, 'text') || getStringValue(match, 'excerpt')),
      start: getNumberValue(match, 'start') ?? 0,
      duration: getNumberValue(match, 'duration') ?? 0,
    }))
    : []
);

export const normalizeSemanticSearchResult = (result: unknown): SemanticSearchResult => {
  const record: Record<string, unknown> = isRecord(result) ? result : {};
  const semanticScore = getNumberValue(record, 'semantic_score') ?? getNumberValue(record, 'score') ?? getNumberValue(record, 'similarity');

  const normalized = normalizeSearchResult({
    video_id: getStringValue(record, 'video_id') || getStringValue(record, 'id'),
    title: getStringValue(record, 'title'),
    channel: getStringValue(record, 'channel'),
    saved_at: getStringValue(record, 'saved_at'),
    uploaded_at: getStringValue(record, 'uploaded_at') || undefined,
    score: semanticScore ?? 0,
    matches: normalizeSearchMatches(record.matches),
    word_count: getNumberValue(record, 'word_count'),
    runtime_seconds: getNumberValue(record, 'runtime_seconds'),
    duration_seconds: getNumberValue(record, 'duration_seconds'),
    segment_count: getNumberValue(record, 'segment_count'),
    match_count: getNumberValue(record, 'match_count'),
  });

  return {
    ...normalized,
    semantic_score: getNumberValue(record, 'semantic_score'),
    similarity: getNumberValue(record, 'similarity'),
    excerpt: decodeDisplayText(getStringValue(record, 'excerpt') || getStringValue(record, 'text')) || undefined,
    reason: decodeDisplayText(getStringValue(record, 'reason')) || undefined,
  };
};

export const normalizeEmbeddingStatus = (data: unknown): EmbeddingStatus => {
  const record: Record<string, unknown> = isRecord(data) ? data : {};

  return {
    exists: getBooleanValue(record, 'exists'),
    path: getStringValue(record, 'path') || undefined,
    embedding_model: getStringValue(record, 'embedding_model') || undefined,
    chunk_count: getNumberValue(record, 'chunk_count') ?? 0,
    stale_count: getNumberValue(record, 'stale_count') ?? 0,
    stale_video_ids: parseStringList(record.stale_video_ids),
  };
};

export const normalizeMCPStatus = (data: unknown): MCPStatus => {
  const record: Record<string, unknown> = isRecord(data) ? data : {};
  const config = isRecord(record.config) ? record.config : {};
  const settings = isRecord(record.settings) ? record.settings : {};

  return {
    enabled: getBooleanValue(record, 'enabled', emptyMCPStatus.enabled),
    read_only: getBooleanValue(record, 'read_only', true),
    server_name: getStringValue(record, 'server_name') || emptyMCPStatus.server_name,
    tools: parseStringList(record.tools),
    storage_backend: getStringValue(record, 'storage_backend') || emptyMCPStatus.storage_backend,
    config: {
      path: getStringValue(config, 'path'),
      exists: getBooleanValue(config, 'exists'),
    },
    settings: {
      updated_at: getStringValue(settings, 'updated_at') || null,
    },
  };
};

export const normalizeSystemStatus = (data: unknown): SystemStatus => {
  const record: Record<string, unknown> = isRecord(data) ? data : {};
  const settings = isRecord(record.settings) ? record.settings : {};
  const backend = isRecord(record.backend) ? record.backend : {};
  const watcher = isRecord(record.watcher) ? record.watcher : {};

  return {
    settings: {
      ingestion_paused: getBooleanValue(settings, 'ingestion_paused'),
      maintenance_mode: getBooleanValue(settings, 'maintenance_mode'),
      updated_at: getStringValue(settings, 'updated_at') || null,
    },
    backend: {
      online: getBooleanValue(backend, 'online'),
      restart_supported: getBooleanValue(backend, 'restart_supported'),
      shutdown_supported: getBooleanValue(backend, 'shutdown_supported'),
      message: getStringValue(backend, 'message') || undefined,
    },
    watcher: {
      thread_alive: getBooleanValue(watcher, 'thread_alive'),
      stop_requested: getBooleanValue(watcher, 'stop_requested'),
    },
  };
};
