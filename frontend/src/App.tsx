import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  Bookmark,
  Bot,
  Brain,
  Calendar,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Clock,
  Copy,
  Cpu,
  Database,
  Download,
  ExternalLink,
  FileText,
  FileDown,
  FileUp,
  Filter,
  FolderPlus,
  Hash,
  ListPlus,
  MessageSquare,
  Play,
  Plug,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Tag,
  Trash2,
  User,
  WandSparkles,
  X,
  Youtube,
} from 'lucide-react';

import { API_BASE, SAVED_SEARCHES_KEY, emptyAIModels, emptyAISettings, emptyMCPStatus, emptyResearchOrganization, emptySystemStatus, emptyWatcherSettings } from './lib/constants';
import { getApiErrorDetails, getApiErrorSummary, isConnectivityError } from './lib/errors';
import { createAISettingsDraft, decodeDisplayText, getArrayValue, getBooleanValue, getNumberValue, getStringValue, isRecord, normalizeAIArtifacts, normalizeAIModels, normalizeAISettings, normalizeAISummary, normalizeEmbeddingStatus, normalizeMCPStatus, normalizeSearchResult, normalizeSemanticSearchResult, normalizeSystemStatus, normalizeTranscript, parseStringList } from './lib/normalize';
import { countQueryMatches, countWords, formatDisplayDateTime, getDisplayDateValue, getQueryTerms, getTranscriptRuntime, parseDisplayDateMillis, parseSavedSearches } from './lib/format';
import { fieldClass, iconButtonClass, panelClass, primaryButtonClass, secondaryButtonClass } from './lib/styles';
import type {
  ArchivedVideo,
  ArchiveStorage,
  AIArtifact,
  AIHealthResult,
  AIModelOptions,
  AISettings,
  AISettingsDraft,
  AITranscriptSummary,
  ActiveView,
  BackendEvent,
  ChannelPreview,
  DataExportFormat,
  DataExportScope,
  DataTableResponse,
  DataTableSummary,
  EmbeddingStatus,
  FetchRun,
  LibraryStats,
  LogEntry,
  LogType,
  MCPStatus,
  ResearchOrganization,
  SearchResult,
  Segment,
  SemanticSearchResult,
  SettingsSection,
  SortOption,
  StorageStatus,
  SystemStatus,
  TaskStatus,
  TimestampNote,
  Transcript,
  WatcherSettings,
} from './types';

function App() {
  const [activeView, setActiveView] = useState<ActiveView>('library');
  const [activeSettingsSection, setActiveSettingsSection] = useState<SettingsSection>('automation');
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTranscript, setCurrentTranscript] = useState<Transcript | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [channelUrl, setChannelUrl] = useState('');
  const [channelLimit, setChannelLimit] = useState('30');
  const [channelPreview, setChannelPreview] = useState<ChannelPreview | null>(null);
  const [channelPreviewBusy, setChannelPreviewBusy] = useState(false);
  const [followingChannel, setFollowingChannel] = useState(false);
  const [followBusy, setFollowBusy] = useState(false);
  const [speechAvailable, setSpeechAvailable] = useState(false);
  const [downloaderUrl, setDownloaderUrl] = useState('');
  const [archivedIds, setArchivedIds] = useState<string[]>([]);
  const [archiveStorage, setArchiveStorage] = useState<ArchiveStorage | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [playingOffline, setPlayingOffline] = useState(false);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([]);
  const [channelFilter, setChannelFilter] = useState('all');
  const [status, setStatus] = useState<TaskStatus>({ current_task: null, progress: 0, total: 0, message: 'Idle' });
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [sortBy, setSortBy] = useState<SortOption>('relevance');
  const [savedSearches, setSavedSearches] = useState<string[]>(() => parseSavedSearches());
  const [storageStatus, setStorageStatus] = useState<StorageStatus | null>(null);
  const [storageBusy, setStorageBusy] = useState(false);
  const [watcherSettings, setWatcherSettings] = useState<WatcherSettings>(emptyWatcherSettings);
  const [settingsDraft, setSettingsDraft] = useState({
    enabled: false,
    channelsText: '',
    frequencyMinutes: '360',
    languagesText: 'en',
  });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [aiSettings, setAISettings] = useState<AISettings>(emptyAISettings);
  const [aiSettingsDraft, setAISettingsDraft] = useState<AISettingsDraft>(() => createAISettingsDraft(emptyAISettings));
  const [aiSettingsLoaded, setAISettingsLoaded] = useState(false);
  const [aiSettingsBusy, setAISettingsBusy] = useState(false);
  const [aiModels, setAIModels] = useState<AIModelOptions>(emptyAIModels);
  const [aiModelsLoading, setAIModelsLoading] = useState(false);
  const [aiArtifacts, setAIArtifacts] = useState<AIArtifact[]>([]);
  const [aiArtifactsLoading, setAIArtifactsLoading] = useState(false);
  const [aiHealth, setAIHealth] = useState<AIHealthResult | null>(null);
  const [aiHealthLoading, setAIHealthLoading] = useState(false);
  const [fetchRuns, setFetchRuns] = useState<FetchRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<FetchRun | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);
  const [researchOrg, setResearchOrg] = useState<ResearchOrganization>(emptyResearchOrganization);
  const [selectedCollectionId, setSelectedCollectionId] = useState('');
  const [newCollectionName, setNewCollectionName] = useState('');
  const [newCollectionDescription, setNewCollectionDescription] = useState('');
  const [tagDraft, setTagDraft] = useState('');
  const [videoNoteDraft, setVideoNoteDraft] = useState('');
  const [timestampNoteDrafts, setTimestampNoteDrafts] = useState<Record<string, string>>({});
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [transcriptsLoading, setTranscriptsLoading] = useState(false);
  const [fetchRequestBusy, setFetchRequestBusy] = useState(false);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [transcriptCollapsed, setTranscriptCollapsed] = useState(false);
  const [summaryByVideoId, setSummaryByVideoId] = useState<Record<string, AITranscriptSummary | null>>({});
  const [summaryLoadingId, setSummaryLoadingId] = useState<string | null>(null);
  const [summaryGeneratingId, setSummaryGeneratingId] = useState<string | null>(null);
  const [semanticQuery, setSemanticQuery] = useState('');
  const [semanticResults, setSemanticResults] = useState<SemanticSearchResult[]>([]);
  const [semanticSearchLoading, setSemanticSearchLoading] = useState(false);
  const [semanticSearchSubmitted, setSemanticSearchSubmitted] = useState(false);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [embeddingBusy, setEmbeddingBusy] = useState(false);
  const [compareVideoIds, setCompareVideoIds] = useState<string[]>([]);
  const [comparisonOutput, setComparisonOutput] = useState<AIArtifact | null>(null);
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const [timelineOutput, setTimelineOutput] = useState<AIArtifact | null>(null);
  const [timelineBusy, setTimelineBusy] = useState(false);
  const [mcpStatus, setMcpStatus] = useState<MCPStatus>(emptyMCPStatus);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [systemStatus, setSystemStatus] = useState<SystemStatus>(emptySystemStatus);
  const [systemBusy, setSystemBusy] = useState(false);
  const [dataTables, setDataTables] = useState<DataTableSummary[]>([]);
  const [selectedDataTable, setSelectedDataTable] = useState('videos');
  const [dataTable, setDataTable] = useState<DataTableResponse | null>(null);
  const [dataTableQuery, setDataTableQuery] = useState('');
  const [dataBusy, setDataBusy] = useState(false);
  const [dataExportDraft, setDataExportDraft] = useState<{
    scope: DataExportScope;
    format: DataExportFormat;
    channel: string;
    collectionId: string;
    query: string;
    includeSegments: boolean;
  }>({
    scope: 'all',
    format: 'json',
    channel: 'all',
    collectionId: '',
    query: '',
    includeSegments: true,
  });
  const [newWatcherChannel, setNewWatcherChannel] = useState('');
  const latestBackendEventId = useRef(0);
  const seenBackendEventIds = useRef<Set<number>>(new Set());
  const logIdSequence = useRef(0);
  const apiOfflineLogged = useRef(false);

  const addLog = useCallback((msg: string, type: LogType = 'info', details?: Record<string, unknown>) => {
    const newLog: LogEntry = {
      id: `frontend-${logIdSequence.current++}`,
      msg,
      type,
      details,
      source: 'frontend',
      time: new Date().toLocaleTimeString(),
    };
    setLogs(prev => [newLog, ...prev].slice(0, 120));
  }, []);

  const addBackendLogs = useCallback((events: BackendEvent[]) => {
    if (events.length === 0) return;

    const unseenEvents = events.filter(event => {
      if (seenBackendEventIds.current.has(event.id)) {
        return false;
      }
      seenBackendEventIds.current.add(event.id);
      return true;
    });
    if (unseenEvents.length === 0) return;

    const backendLogs: LogEntry[] = unseenEvents.slice().reverse().map(event => ({
      id: `backend-${event.id}-${logIdSequence.current++}`,
      msg: event.message,
      type: event.level === 'warning' ? 'warning' : event.level === 'error' ? 'error' : event.level === 'success' ? 'success' : 'info',
      time: new Date(event.timestamp).toLocaleTimeString(),
      source: 'backend',
      event: event.event,
      details: event.details,
    }));
    latestBackendEventId.current = Math.max(latestBackendEventId.current, ...unseenEvents.map(event => event.id));
    setLogs(prev => {
      const existingIds = new Set(prev.map(log => log.id));
      return [
        ...backendLogs.filter(log => !existingIds.has(log.id)),
        ...prev,
      ].slice(0, 120);
    });
  }, []);

  const markApiOnline = useCallback(() => {
    setApiConnected(true);
    if (apiOfflineLogged.current) {
      addLog('Backend connection restored', 'success');
      apiOfflineLogged.current = false;
    }
  }, [addLog]);

  const markApiOffline = useCallback((message: string, error: unknown) => {
    setApiConnected(false);
    if (!apiOfflineLogged.current) {
      addLog(`${message}: ${getApiErrorSummary(error)}`, 'error', getApiErrorDetails(error));
      apiOfflineLogged.current = true;
    }
  }, [addLog]);

  const reportApiError = useCallback((message: string, error: unknown) => {
    if (isConnectivityError(error)) {
      markApiOffline(message, error);
      return;
    }

    if (axios.isAxiosError(error) && error.response) {
      setApiConnected(true);
    }
    addLog(`${message}: ${getApiErrorSummary(error)}`, 'error', getApiErrorDetails(error));
  }, [addLog, markApiOffline]);

  const fetchTranscripts = useCallback(async () => {
    setTranscriptsLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/transcripts`);
      const normalized = (res.data as Transcript[]).map(normalizeTranscript);
      setTranscripts(normalized);
      markApiOnline();
      addLog(`Loaded ${normalized.length} transcripts`, 'info');
    } catch (error) {
      reportApiError('Failed to fetch transcripts', error);
    } finally {
      setTranscriptsLoading(false);
    }
  }, [addLog, markApiOnline, reportApiError]);

  const fetchLibraryStats = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/stats`);
      const stats: LibraryStats = res.data;
      setLibraryStats({
        ...stats,
        channel_counts: stats.channel_counts.map(channel => ({
          ...channel,
          channel: decodeDisplayText(channel.channel),
        })),
      });
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch library stats', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchStorageStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/storage/status`);
      setStorageStatus(res.data);
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch storage status', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchMcpStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/mcp/status`);
      setMcpStatus(normalizeMCPStatus(res.data));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch MCP status', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchSystemStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/system/status`);
      setSystemStatus(normalizeSystemStatus(res.data));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch system status', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchDataTables = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/data/tables`);
      const tables = isRecord(res.data) ? getArrayValue(res.data, 'tables').filter(isRecord).map(table => ({
        name: getStringValue(table, 'name'),
        count: getNumberValue(table, 'count') ?? 0,
        columns: parseStringList(table.columns),
      })).filter(table => table.name) : [];
      setDataTables(tables);
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch data tables', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchDataTable = useCallback(async (tableName: string, query = '') => {
    setDataBusy(true);
    try {
      const res = await axios.get(`${API_BASE}/data/tables/${tableName}`, {
        params: { limit: 80, q: query },
      });
      const payload = isRecord(res.data) ? res.data : {};
      setDataTable({
        name: getStringValue(payload, 'name') || tableName,
        columns: parseStringList(payload.columns),
        rows: getArrayValue(payload, 'rows').filter(isRecord),
        total: getNumberValue(payload, 'total') ?? 0,
        limit: getNumberValue(payload, 'limit') ?? 80,
        offset: getNumberValue(payload, 'offset') ?? 0,
      });
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch data table', error);
    } finally {
      setDataBusy(false);
    }
  }, [markApiOnline, reportApiError]);

  const fetchArchive = useCallback(async () => {
    try {
      const res = await axios.get<{ items: ArchivedVideo[]; storage: ArchiveStorage }>(`${API_BASE}/archive`);
      setArchivedIds(res.data.items.map(item => item.video_id));
      setArchiveStorage(res.data.storage);
    } catch {
      setArchivedIds([]);
      setArchiveStorage(null);
    }
  }, []);

  useEffect(() => { fetchArchive(); }, [fetchArchive]);

  const fetchWatcherSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/watcher/settings`);
      const settings: WatcherSettings = { ...emptyWatcherSettings, ...res.data };
      setWatcherSettings(settings);
      setSettingsDraft({
        enabled: settings.enabled,
        channelsText: settings.channels.join('\n'),
        frequencyMinutes: String(settings.frequency_minutes),
        languagesText: settings.languages.join(', '),
      });
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch watcher settings', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchAISettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/ai/settings`);
      const settings = normalizeAISettings(res.data);
      setAISettings(settings);
      setAISettingsDraft(createAISettingsDraft(settings));
      setAISettingsLoaded(true);
      markApiOnline();
    } catch (error) {
      setAISettingsLoaded(false);
      reportApiError('Failed to fetch AI settings', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchAIModels = useCallback(async () => {
    setAIModelsLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/ai/models`);
      setAIModels(normalizeAIModels(res.data));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch AI models', error);
    } finally {
      setAIModelsLoading(false);
    }
  }, [markApiOnline, reportApiError]);

  const fetchAIArtifacts = useCallback(async () => {
    setAIArtifactsLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/ai/artifacts`);
      setAIArtifacts(normalizeAIArtifacts(res.data));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch AI artifacts', error);
    } finally {
      setAIArtifactsLoading(false);
    }
  }, [markApiOnline, reportApiError]);

  const fetchEmbeddingStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/ai/embeddings/status`);
      setEmbeddingStatus(normalizeEmbeddingStatus(res.data));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch embedding status', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchTranscriptSummary = useCallback(async (videoId: string) => {
    setSummaryLoadingId(videoId);
    try {
      const res = await axios.get(`${API_BASE}/ai/transcripts/${videoId}/summary`);
      const summary = normalizeAISummary(res.data, videoId);
      setSummaryByVideoId(prev => ({ ...prev, [videoId]: summary }));
      markApiOnline();
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        setSummaryByVideoId(prev => ({ ...prev, [videoId]: null }));
        markApiOnline();
        return;
      }
      reportApiError('Failed to fetch AI summary', error);
    } finally {
      setSummaryLoadingId(prev => prev === videoId ? null : prev);
    }
  }, [markApiOnline, reportApiError]);

  const fetchFetchRuns = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/fetch/runs`, {
        params: { limit: 30 },
      });
      const runs: FetchRun[] = res.data.runs ?? [];
      setFetchRuns(runs);
      setSelectedRunId(prev => {
        if (prev && runs.some(run => run.id === prev)) {
          return prev;
        }
        return runs[0]?.id ?? '';
      });
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch run history', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchFetchRun = useCallback(async (runId: string) => {
    if (!runId) {
      setSelectedRun(null);
      return;
    }

    setRunLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/fetch/runs/${runId}`);
      setSelectedRun(res.data);
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch run details', error);
      setSelectedRun(null);
    } finally {
      setRunLoading(false);
    }
  }, [markApiOnline, reportApiError]);

  const fetchResearchOrganization = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/research`);
      setResearchOrg({
        ...emptyResearchOrganization,
        ...res.data,
      });
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to fetch research organization data', error);
    }
  }, [markApiOnline, reportApiError]);

  const fetchBackendEvents = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/events`, {
        params: { after: latestBackendEventId.current, limit: 100 },
      });
      markApiOnline();
      addBackendLogs(res.data.events ?? []);
    } catch (error) {
      markApiOffline('Backend event stream unavailable', error);
    }
  }, [addBackendLogs, markApiOffline, markApiOnline]);

  useEffect(() => {
    fetchTranscripts();
    fetchLibraryStats();
    fetchStorageStatus();
    fetchWatcherSettings();
    fetchFetchRuns();
    fetchResearchOrganization();
    fetchBackendEvents();
    fetchAISettings();
    fetchEmbeddingStatus();
    fetchMcpStatus();
    fetchSystemStatus();
    fetchDataTables();
    addLog('System initialized', 'success');

    let lastTask: string | null = null;
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/status`);
        const newStatus = res.data;
        setStatus(newStatus);
        markApiOnline();

        if (newStatus.current_task && newStatus.current_task !== lastTask) {
          addLog(`Task running: ${newStatus.message}`, 'info', {
            task: newStatus.current_task,
            run_id: newStatus.run_id,
          });
        }
        if (!newStatus.current_task && lastTask) {
          addLog(`Task finished: ${lastTask}`, 'success');
          fetchTranscripts();
          fetchLibraryStats();
          fetchStorageStatus();
          fetchFetchRuns();
          fetchWatcherSettings();
          fetchResearchOrganization();
          fetchAIArtifacts();
          fetchEmbeddingStatus();
          fetchSystemStatus();
          fetchDataTables();
          fetchArchive();
        }
        lastTask = newStatus.current_task;
        fetchBackendEvents();
      } catch (err) {
        markApiOffline('Backend status polling failed', err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [addLog, fetchAIArtifacts, fetchAISettings, fetchBackendEvents, fetchDataTables, fetchEmbeddingStatus, fetchFetchRuns, fetchLibraryStats, fetchMcpStatus, fetchResearchOrganization, fetchStorageStatus, fetchSystemStatus, fetchTranscripts, fetchWatcherSettings, fetchArchive, markApiOffline, markApiOnline]);

  useEffect(() => {
    if (activeView === 'settings' && selectedRunId) {
      fetchFetchRun(selectedRunId);
    }
  }, [activeView, fetchFetchRun, selectedRunId]);

  useEffect(() => {
    if (activeView !== 'settings') return;
    fetchAISettings();
    fetchAIModels();
    fetchAIArtifacts();
    fetchEmbeddingStatus();
    fetchMcpStatus();
    fetchSystemStatus();
    fetchDataTables();
  }, [activeView, fetchAIArtifacts, fetchAIModels, fetchAISettings, fetchDataTables, fetchEmbeddingStatus, fetchMcpStatus, fetchSystemStatus]);

  useEffect(() => {
    if (activeView !== 'settings' || activeSettingsSection !== 'data') return;
    fetchDataTable(selectedDataTable, dataTableQuery);
  }, [activeSettingsSection, activeView, dataTableQuery, fetchDataTable, selectedDataTable]);

  useEffect(() => {
    window.localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(savedSearches));
  }, [savedSearches]);

  useEffect(() => {
    if (researchOrg.collections.length === 0) {
      setSelectedCollectionId('');
      return;
    }

    if (!selectedCollectionId || !researchOrg.collections.some(collection => collection.id === selectedCollectionId)) {
      setSelectedCollectionId(researchOrg.collections[0].id);
    }
  }, [researchOrg.collections, selectedCollectionId]);

  useEffect(() => {
    if (!currentTranscript) {
      setTagDraft('');
      setVideoNoteDraft('');
      setTimestampNoteDrafts({});
      return;
    }

    setTagDraft((researchOrg.tags[currentTranscript.video_id] ?? []).join(', '));
    setVideoNoteDraft(researchOrg.video_notes[currentTranscript.video_id] ?? '');
    setTimestampNoteDrafts({});
  }, [currentTranscript, researchOrg.tags, researchOrg.video_notes]);

  useEffect(() => {
    setTranscriptCollapsed(false);
  }, [currentTranscript?.video_id]);

  useEffect(() => {
    if (!currentTranscript?.video_id) return;
    fetchTranscriptSummary(currentTranscript.video_id);
  }, [currentTranscript?.video_id, fetchTranscriptSummary]);

  useEffect(() => {
    const query = searchQuery.trim();
    const controller = new AbortController();

    if (query.length < 2) {
      setSearchResults([]);
      setSearchLoading(false);
      return () => controller.abort();
    }

    const timer = window.setTimeout(async () => {
      const params = new URLSearchParams({ q: query, limit: '20' });
      if (channelFilter !== 'all') {
        params.set('channel', channelFilter);
      }
      params.set('sort', sortBy === 'most_matches' ? 'matches' : sortBy);

      setSearchLoading(true);
      try {
        const res = await axios.get(`${API_BASE}/search?${params.toString()}`, {
          signal: controller.signal,
        });
        setSearchResults((res.data as SearchResult[]).map(normalizeSearchResult));
      } catch (error) {
        if (!axios.isCancel(error)) {
          reportApiError('Failed to search transcripts', error);
        }
      } finally {
        setSearchLoading(false);
      }
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [channelFilter, reportApiError, searchQuery, sortBy]);

  const handleSelect = async (id: string) => {
    setActiveView('library');
    setSelectedId(id);
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/transcripts/${id}`);
      const transcript = normalizeTranscript(res.data);
      setCurrentTranscript(transcript);
      markApiOnline();
      addLog(`Selected: ${transcript.title}`, 'info');
    } catch (error) {
      reportApiError('Failed to fetch transcript details', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this transcript?')) return;
    try {
      await axios.delete(`${API_BASE}/transcripts/${id}`);
      if (selectedId === id) {
        setSelectedId(null);
        setCurrentTranscript(null);
      }
      addLog(`Deleted transcript: ${id}`, 'success');
      await fetchTranscripts();
      await fetchLibraryStats();
    } catch (error) {
      reportApiError('Failed to delete transcript', error);
    }
  };

  const handleFetchVideo = async () => {
    if (!videoUrl.trim() || fetchRequestBusy || status.current_task) return;
    setFetchRequestBusy(true);
    try {
      addLog(`Starting fetch for video: ${videoUrl}`, 'info');
      const res = await axios.post(`${API_BASE}/fetch/video`, { url: videoUrl });
      markApiOnline();
      setStatus(prev => ({
        ...prev,
        run_id: res.data.run_id,
        current_task: 'video',
        progress: 0,
        total: 1,
        message: 'Video fetch accepted. Waiting for transcript worker...',
        success_count: 0,
        failure_count: 0,
        skipped_count: 0,
      }));
      addLog('Video fetch accepted by backend', 'success', res.data);
      setVideoUrl('');
    } catch (error) {
      reportApiError('Failed to trigger video fetch', error);
    } finally {
      setFetchRequestBusy(false);
    }
  };

  // Joined rather than the array itself: a fresh array on every settings poll
  // would re-run the check below and cancel the one already in flight.
  const followedChannelsKey = watcherSettings.channels.join('|');

  useEffect(() => {
    const channel = channelUrl.trim();
    if (!channel) {
      setFollowingChannel(false);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await axios.get(`${API_BASE}/watcher/following`, { params: { channel } });
        if (!cancelled) setFollowingChannel(Boolean(res.data.following));
      } catch {
        if (!cancelled) setFollowingChannel(false);
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [channelUrl, followedChannelsKey]);

  const handleToggleFollow = async () => {
    const channel = channelUrl.trim();
    if (!channel || followBusy) return;
    setFollowBusy(true);
    try {
      const path = followingChannel ? 'unfollow' : 'follow';
      const res = await axios.post(`${API_BASE}/watcher/${path}`, { channel });
      markApiOnline();
      setFollowingChannel(Boolean(res.data.following));
      setWatcherSettings(prev => ({ ...prev, channels: res.data.channels ?? prev.channels }));
      addLog(
        res.data.following ? `Following ${channel}` : `Stopped following ${channel}`,
        'success',
      );
      fetchWatcherSettings();
    } catch (error) {
      reportApiError('Failed to update followed channels', error);
    } finally {
      setFollowBusy(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [speech, downloader] = await Promise.all([
          axios.get(`${API_BASE}/speech/status`),
          axios.get(`${API_BASE}/downloader`),
        ]);
        if (cancelled) return;
        setSpeechAvailable(Boolean(speech.data.available));
        setDownloaderUrl(downloader.data.configured ? String(downloader.data.url) : '');
      } catch {
        if (!cancelled) {
          setSpeechAvailable(false);
          setDownloaderUrl('');
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);


  const handleArchiveVideo = async () => {
    if (!currentTranscript || archiveBusy || status.current_task) return;
    setArchiveBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/archive`, {
        video_id: currentTranscript.video_id,
        quality: '720p',
      });
      markApiOnline();
      if (res.data.status === 'already_archived') {
        addLog('Already archived', 'info');
        fetchArchive();
      } else {
        setStatus(prev => ({ ...prev, run_id: res.data.run_id, current_task: 'archive', progress: 0, total: 1,
          message: 'Archive queued...', success_count: 0, failure_count: 0, skipped_count: 0 }));
        addLog(`Archiving ${currentTranscript.title}`, 'info');
      }
    } catch (error) {
      reportApiError('Failed to archive video', error);
    } finally {
      setArchiveBusy(false);
    }
  };

  const handleDeleteArchived = async () => {
    if (!currentTranscript) return;
    if (!confirm('Delete the stored video file? The transcript is kept.')) return;
    try {
      await axios.delete(`${API_BASE}/archive/${currentTranscript.video_id}`);
      addLog('Deleted archived video file', 'success');
      setPlayingOffline(false);
      fetchArchive();
    } catch (error) {
      reportApiError('Failed to delete archived video', error);
    }
  };

  const handleTranscribeBySpeech = async () => {
    if (!currentTranscript || fetchRequestBusy || status.current_task) return;
    const url = currentTranscript.source_url || `https://www.youtube.com/watch?v=${currentTranscript.video_id}`;
    setFetchRequestBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/fetch/speech`, { url, diarize: true });
      markApiOnline();
      setStatus(prev => ({ ...prev, run_id: res.data.run_id, current_task: 'speech', progress: 0, total: 1,
        message: 'Speech transcription queued...', success_count: 0, failure_count: 0, skipped_count: 0 }));
      addLog(`Re-transcribing ${currentTranscript.title} from audio`, 'info');
    } catch (error) {
      reportApiError('Failed to start speech transcription', error);
    } finally {
      setFetchRequestBusy(false);
    }
  };

  const parsedChannelLimit = () => {
    const value = Number.parseInt(channelLimit, 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  };

  const handlePreviewChannel = async () => {
    if (!channelUrl.trim() || channelPreviewBusy) return;
    setChannelPreviewBusy(true);
    try {
      addLog(`Listing recent videos for channel: ${channelUrl}`, 'info');
      const res = await axios.post<ChannelPreview>(`${API_BASE}/fetch/channel/preview`, {
        url: channelUrl,
        limit: parsedChannelLimit(),
        skip_existing: true,
      });
      markApiOnline();
      setChannelPreview(res.data);
      setSelectedCandidates(res.data.candidates.filter(item => item.selected).map(item => item.video_id));
      addLog(
        `Listed ${res.data.total} videos via ${res.data.listing_source}: ${res.data.new_count} new, ${res.data.already_saved_count} already archived`,
        'success',
      );
    } catch (error) {
      reportApiError('Failed to list channel videos', error);
    } finally {
      setChannelPreviewBusy(false);
    }
  };

  const toggleCandidate = (videoId: string) => {
    setSelectedCandidates(prev =>
      prev.includes(videoId) ? prev.filter(id => id !== videoId) : [...prev, videoId],
    );
  };

  const handleFetchChannel = async (videoIds?: string[]) => {
    if (!channelUrl.trim() || fetchRequestBusy || status.current_task) return;
    setFetchRequestBusy(true);
    try {
      const scope = videoIds?.length ? `${videoIds.length} selected videos` : `latest ${channelLimit || 'all'}`;
      addLog(`Starting bulk fetch for channel: ${channelUrl} (${scope})`, 'info');
      const res = await axios.post(`${API_BASE}/fetch/channel`, {
        url: channelUrl,
        limit: parsedChannelLimit(),
        skip_existing: true,
        video_ids: videoIds?.length ? videoIds : null,
      });
      markApiOnline();
      setStatus(prev => ({
        ...prev,
        run_id: res.data.run_id,
        current_task: 'channel',
        progress: 0,
        total: 0,
        message: 'Channel fetch accepted. Finding videos...',
        success_count: 0,
        failure_count: 0,
        skipped_count: 0,
      }));
      addLog('Channel fetch accepted by backend', 'success', res.data);
      setChannelPreview(null);
      setSelectedCandidates([]);
    } catch (error) {
      reportApiError('Failed to trigger channel fetch', error);
    } finally {
      setFetchRequestBusy(false);
    }
  };

  const handleMigrateStorage = async () => {
    if (storageBusy) return;
    if (!confirm('Migrate the local JSON transcript store into SQLite and use SQLite for this session?')) return;

    setStorageBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/storage/migrate`);
      setStorageStatus(res.data.storage);
      markApiOnline();
      addLog(`SQLite migration complete: ${res.data.storage.active_count} transcripts active`, 'success');
      await fetchTranscripts();
      await fetchLibraryStats();
      await fetchStorageStatus();
    } catch (error) {
      reportApiError('Failed to migrate storage to SQLite', error);
    } finally {
      setStorageBusy(false);
    }
  };

  const handleExportJson = async () => {
    if (storageBusy) return;

    setStorageBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/storage/export-json`);
      markApiOnline();
      addLog(`Exported ${res.data.count} transcripts to ${res.data.path}`, 'success');
      await fetchStorageStatus();
    } catch (error) {
      reportApiError('Failed to export JSON backup', error);
    } finally {
      setStorageBusy(false);
    }
  };

  const parseSettingsLines = (value: string) => (
    Array.from(new Set(value.split(/[,\n]/).map(item => item.trim()).filter(Boolean)))
  );

  const handleAddWatcherChannel = () => {
    const channel = newWatcherChannel.trim();
    if (!channel) return;

    setSettingsDraft(prev => ({
      ...prev,
      channelsText: [...parseSettingsLines(prev.channelsText), channel].join('\n'),
    }));
    setNewWatcherChannel('');
  };

  const handleRemoveWatcherChannel = (channel: string) => {
    setSettingsDraft(prev => ({
      ...prev,
      channelsText: parseSettingsLines(prev.channelsText).filter(item => item !== channel).join('\n'),
    }));
  };

  const handleToggleMCP = async () => {
    if (mcpBusy) return;

    setMcpBusy(true);
    try {
      const res = await axios.put(`${API_BASE}/mcp/settings`, { enabled: !mcpStatus.enabled });
      setMcpStatus(normalizeMCPStatus(res.data));
      markApiOnline();
      addLog(`MCP ${!mcpStatus.enabled ? 'enabled' : 'disabled'}`, 'success');
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to update MCP settings', error);
    } finally {
      setMcpBusy(false);
    }
  };

  const handleUpdateSystemSettings = async (updates: Partial<SystemStatus['settings']>) => {
    if (systemBusy) return;

    setSystemBusy(true);
    try {
      const res = await axios.put(`${API_BASE}/system/settings`, updates);
      setSystemStatus(normalizeSystemStatus(res.data));
      markApiOnline();
      addLog('System controls updated', 'success');
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to update system controls', error);
    } finally {
      setSystemBusy(false);
    }
  };

  const handleCancelTask = async () => {
    if (systemBusy || !status.current_task) return;

    setSystemBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/system/cancel-task`);
      if (isRecord(res.data) && isRecord(res.data.task)) {
        setStatus(res.data.task as unknown as TaskStatus);
      }
      markApiOnline();
      addLog('Cancel requested for active task', 'warning');
      await fetchSystemStatus();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to request task cancel', error);
    } finally {
      setSystemBusy(false);
    }
  };

  const buildAISettingsPayload = () => {
    const timeoutSeconds = Math.max(1, Number.parseInt(aiSettingsDraft.timeoutSeconds, 10) || emptyAISettings.timeout_seconds);
    const temperature = Math.min(2, Math.max(0, Number.parseFloat(aiSettingsDraft.temperature) || 0));

    return {
      enabled: aiSettingsDraft.enabled,
      provider: aiSettingsDraft.provider.trim(),
      base_url: aiSettingsDraft.baseUrl.trim(),
      summary_model: aiSettingsDraft.summaryModel.trim(),
      embedding_model: aiSettingsDraft.embeddingModel.trim(),
      timeout_seconds: timeoutSeconds,
      temperature,
      ...(aiSettings.prompt_version ? { prompt_version: aiSettings.prompt_version } : {}),
    };
  };

  const handleSaveAISettings = async () => {
    if (aiSettingsBusy) return;

    setAISettingsBusy(true);
    try {
      const res = await axios.put(`${API_BASE}/ai/settings`, buildAISettingsPayload());
      const settings = normalizeAISettings(res.data);
      setAISettings(settings);
      setAISettingsDraft(createAISettingsDraft(settings));
      setAISettingsLoaded(true);
      markApiOnline();
      addLog('AI settings saved', 'success');
      await fetchAIModels();
      await fetchAIArtifacts();
      await fetchEmbeddingStatus();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to save AI settings', error);
    } finally {
      setAISettingsBusy(false);
    }
  };

  const handleTestAIConnection = async () => {
    if (aiHealthLoading) return;

    setAIHealthLoading(true);
    setAIHealth(null);
    try {
      const res = await axios.post(`${API_BASE}/ai/health`, buildAISettingsPayload());
      const health: AIHealthResult = isRecord(res.data)
        ? {
          ok: 'ok' in res.data ? getBooleanValue(res.data, 'ok') : undefined,
          success: 'success' in res.data ? getBooleanValue(res.data, 'success') : undefined,
          status: getStringValue(res.data, 'status') || undefined,
          message: getStringValue(res.data, 'message') || undefined,
          provider: getStringValue(res.data, 'provider') || undefined,
          model: getStringValue(res.data, 'model') || undefined,
          latency_ms: getNumberValue(res.data, 'latency_ms'),
        }
        : { ok: true, message: 'Connection test completed' };
      setAIHealth(health);
      markApiOnline();
      const failedStatus = ['error', 'failed', 'unhealthy'].includes((health.status ?? '').toLowerCase());
      addLog(health.message || 'AI connection test completed', health.ok === false || health.success === false || failedStatus ? 'warning' : 'success');
    } catch (error) {
      setAIHealth({
        ok: false,
        message: getApiErrorSummary(error),
      });
      reportApiError('AI connection test failed', error);
    } finally {
      setAIHealthLoading(false);
    }
  };

  const handleGenerateSummary = async () => {
    if (!currentTranscript || summaryGeneratingId) return;

    const videoId = currentTranscript.video_id;
    setSummaryGeneratingId(videoId);
    try {
      const res = await axios.post(`${API_BASE}/ai/transcripts/${videoId}/summary`);
      const summary = normalizeAISummary(res.data, videoId);
      setSummaryByVideoId(prev => ({ ...prev, [videoId]: summary }));
      markApiOnline();
      addLog(`Generated AI summary for ${currentTranscript.title}`, 'success');
      await fetchAIArtifacts();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to generate AI summary', error);
    } finally {
      setSummaryGeneratingId(null);
    }
  };

  const handleSemanticSearch = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const query = semanticQuery.trim();

    if (query.length < 2 || semanticSearchLoading) return;

    setSemanticSearchSubmitted(true);
    setSemanticSearchLoading(true);
    try {
      const params = new URLSearchParams({ q: query, limit: '10' });
      const res = await axios.get(`${API_BASE}/semantic-search?${params.toString()}`);
      const rawResults = Array.isArray(res.data)
        ? res.data
        : isRecord(res.data)
          ? getArrayValue(res.data, 'results')
          : [];
      setSemanticResults(rawResults.map(normalizeSemanticSearchResult));
      markApiOnline();
    } catch (error) {
      reportApiError('Failed to run semantic search', error);
    } finally {
      setSemanticSearchLoading(false);
    }
  };

  const clearSemanticSearch = () => {
    setSemanticQuery('');
    setSemanticResults([]);
    setSemanticSearchSubmitted(false);
    setSemanticSearchLoading(false);
  };

  const toggleCompareVideo = (videoId: string) => {
    setCompareVideoIds(prev => (
      prev.includes(videoId)
        ? prev.filter(id => id !== videoId)
        : [...prev, videoId].slice(-8)
    ));
  };

  const handleRebuildEmbeddings = async () => {
    if (embeddingBusy) return;

    setEmbeddingBusy(true);
    try {
      await axios.post(`${API_BASE}/ai/embeddings/rebuild`, {});
      markApiOnline();
      addLog('Semantic index rebuilt', 'success');
      await fetchEmbeddingStatus();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to rebuild semantic index', error);
    } finally {
      setEmbeddingBusy(false);
    }
  };

  const handleCompareVideos = async () => {
    if (comparisonBusy || compareVideoIds.length < 2) return;

    setComparisonBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/ai/compare`, { video_ids: compareVideoIds });
      const artifact = isRecord(res.data) && isRecord(res.data.comparison)
        ? normalizeAIArtifacts([res.data.comparison])[0]
        : null;
      setComparisonOutput(artifact ?? null);
      markApiOnline();
      addLog('Generated transcript comparison', 'success');
      await fetchAIArtifacts();
    } catch (error) {
      reportApiError('Failed to compare transcripts', error);
    } finally {
      setComparisonBusy(false);
    }
  };

  const handleBuildTimeline = async () => {
    if (timelineBusy) return;

    setTimelineBusy(true);
    try {
      const payload = compareVideoIds.length > 0
        ? { video_ids: compareVideoIds }
        : channelFilter !== 'all'
          ? { channel: channelFilter }
          : { video_ids: transcripts.slice(0, 8).map(transcript => transcript.video_id) };
      const res = await axios.post(`${API_BASE}/ai/timeline`, payload);
      const artifact = isRecord(res.data) && isRecord(res.data.timeline)
        ? normalizeAIArtifacts([res.data.timeline])[0]
        : null;
      setTimelineOutput(artifact ?? null);
      markApiOnline();
      addLog('Generated topic timeline', 'success');
      await fetchAIArtifacts();
    } catch (error) {
      reportApiError('Failed to build topic timeline', error);
    } finally {
      setTimelineBusy(false);
    }
  };

  const handleSaveWatcherSettings = async () => {
    if (settingsBusy) return;

    setSettingsBusy(true);
    try {
      const payload = {
        enabled: settingsDraft.enabled,
        channels: parseSettingsLines(settingsDraft.channelsText),
        frequency_minutes: Math.max(15, Number.parseInt(settingsDraft.frequencyMinutes, 10) || 360),
        languages: parseSettingsLines(settingsDraft.languagesText),
      };
      const res = await axios.put(`${API_BASE}/watcher/settings`, payload);
      markApiOnline();
      const settings: WatcherSettings = { ...emptyWatcherSettings, ...res.data };
      setWatcherSettings(settings);
      setSettingsDraft({
        enabled: settings.enabled,
        channelsText: settings.channels.join('\n'),
        frequencyMinutes: String(settings.frequency_minutes),
        languagesText: settings.languages.join(', '),
      });
      addLog('Watcher settings saved', 'success');
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to save watcher settings', error);
    } finally {
      setSettingsBusy(false);
    }
  };

  const handleRunWatcherNow = async () => {
    if (settingsBusy) return;

    setSettingsBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/watcher/run-now`);
      markApiOnline();
      setStatus(prev => ({
        ...prev,
        run_id: res.data.run_id,
        current_task: 'watcher',
        progress: 0,
        total: 0,
        message: 'Watcher refresh accepted. Checking RSS feeds...',
        success_count: 0,
        failure_count: 0,
        skipped_count: 0,
      }));
      addLog('Watcher refresh started', 'success', res.data);
      setActiveView('settings');
      await fetchFetchRuns();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to start watcher refresh', error);
    } finally {
      setSettingsBusy(false);
    }
  };

  const handleRetryFailedRun = async (runId: string) => {
    if (retryingRunId) return;

    setRetryingRunId(runId);
    try {
      const res = await axios.post(`${API_BASE}/fetch/retry-failed`, { run_id: runId });
      markApiOnline();
      setStatus(prev => ({
        ...prev,
        run_id: res.data.run_id,
        current_task: 'retry',
        progress: 0,
        total: res.data.retry_count ?? 0,
        message: 'Retry run accepted. Refetching failed videos...',
        success_count: 0,
        failure_count: 0,
        skipped_count: 0,
      }));
      addLog('Retry run started', 'success', res.data);
      await fetchFetchRuns();
      await fetchFetchRun(runId);
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to start retry run', error);
    } finally {
      setRetryingRunId(null);
    }
  };

  const parseTags = (value: string) => (
    Array.from(new Set(value.split(/[,\n]/).map(tag => tag.trim().replace(/^#/, '').toLowerCase()).filter(Boolean)))
  );

  const handleSaveTags = async () => {
    if (!currentTranscript) return;

    try {
      const tags = parseTags(tagDraft);
      await axios.put(`${API_BASE}/transcripts/${currentTranscript.video_id}/tags`, { tags });
      setResearchOrg(prev => ({
        ...prev,
        tags: {
          ...prev.tags,
          [currentTranscript.video_id]: tags,
        },
      }));
      addLog(`Saved ${tags.length} tags for ${currentTranscript.video_id}`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to save transcript tags', error);
    }
  };

  const handleSaveVideoNote = async () => {
    if (!currentTranscript) return;

    try {
      await axios.put(`${API_BASE}/transcripts/${currentTranscript.video_id}/note`, {
        note: videoNoteDraft,
      });
      setResearchOrg(prev => ({
        ...prev,
        video_notes: {
          ...prev.video_notes,
          [currentTranscript.video_id]: videoNoteDraft,
        },
      }));
      addLog(`Saved note for ${currentTranscript.video_id}`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to save video note', error);
    }
  };

  const handleCreateCollection = async () => {
    const name = newCollectionName.trim();
    if (!name) return;

    try {
      const res = await axios.post(`${API_BASE}/collections`, {
        name,
        description: newCollectionDescription,
      });
      setSelectedCollectionId(res.data.id);
      setNewCollectionName('');
      setNewCollectionDescription('');
      addLog(`Created collection: ${res.data.name}`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to create collection', error);
    }
  };

  const handleDeleteCollection = async () => {
    if (!selectedCollectionId) return;
    if (!confirm('Delete this collection and all saved clips?')) return;

    try {
      await axios.delete(`${API_BASE}/collections/${selectedCollectionId}`);
      addLog('Deleted collection', 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to delete collection', error);
    }
  };

  const handleSaveClip = async (videoId: string, start: number, text: string, end?: number | null) => {
    if (!selectedCollectionId) {
      addLog('Create or select a collection before saving clips', 'warning');
      return;
    }

    try {
      await axios.post(`${API_BASE}/collections/${selectedCollectionId}/clips`, {
        video_id: videoId,
        start,
        end,
        text,
      });
      addLog(`Saved clip at ${formatTimestamp(start)} to collection`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to save clip', error);
    }
  };

  const handleDeleteClip = async (clipId: string) => {
    if (!selectedCollectionId) return;

    try {
      await axios.delete(`${API_BASE}/collections/${selectedCollectionId}/clips/${clipId}`);
      addLog('Deleted clip from collection', 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to delete collection clip', error);
    }
  };

  const handleAddTimestampNote = async (segment: Segment) => {
    if (!currentTranscript) return;
    const draftKey = `${segment.start}`;
    const text = (timestampNoteDrafts[draftKey] ?? '').trim();
    if (!text) return;

    try {
      await axios.post(`${API_BASE}/transcripts/${currentTranscript.video_id}/timestamp-notes`, {
        start: segment.start,
        text,
      });
      setTimestampNoteDrafts(prev => ({ ...prev, [draftKey]: '' }));
      addLog(`Saved timestamp note at ${formatTimestamp(segment.start)}`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to save timestamp note', error);
    }
  };

  const handleDeleteTimestampNote = async (note: TimestampNote) => {
    try {
      await axios.delete(`${API_BASE}/transcripts/${note.video_id}/timestamp-notes/${note.id}`);
      addLog(`Deleted timestamp note at ${formatTimestamp(note.start)}`, 'success');
      await fetchResearchOrganization();
    } catch (error) {
      reportApiError('Failed to delete timestamp note', error);
    }
  };

  const downloadTextFile = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const downloadBlobFile = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const filenameFromDisposition = (disposition: string | undefined, fallback: string) => {
    const match = disposition?.match(/filename="?([^";]+)"?/i);
    return match?.[1] ?? fallback;
  };

  const handleDataExport = async () => {
    if (dataBusy) return;

    const selectedIds = Array.from(new Set([selectedId, ...compareVideoIds].filter((id): id is string => Boolean(id))));
    const payload = {
      scope: dataExportDraft.scope,
      format: dataExportDraft.format,
      include_segments: dataExportDraft.includeSegments,
      ...(dataExportDraft.scope === 'channel' && dataExportDraft.channel !== 'all' ? { channel: dataExportDraft.channel } : {}),
      ...(dataExportDraft.scope === 'collection' ? { collection_id: dataExportDraft.collectionId || selectedCollectionId } : {}),
      ...(dataExportDraft.scope === 'search' ? { query: dataExportDraft.query || searchQuery, channel: channelFilter !== 'all' ? channelFilter : undefined } : {}),
      ...(dataExportDraft.scope === 'selected' ? { video_ids: selectedIds } : {}),
    };

    if (dataExportDraft.scope === 'channel' && dataExportDraft.channel === 'all') {
      addLog('Choose a channel before exporting a channel scope', 'warning');
      return;
    }
    if (dataExportDraft.scope === 'collection' && !(dataExportDraft.collectionId || selectedCollectionId)) {
      addLog('Choose a collection before exporting collection transcripts', 'warning');
      return;
    }
    if (dataExportDraft.scope === 'search' && !(dataExportDraft.query || searchQuery).trim()) {
      addLog('Enter a search query before exporting search results', 'warning');
      return;
    }
    if (dataExportDraft.scope === 'selected' && selectedIds.length === 0) {
      addLog('Select a transcript before exporting selected transcripts', 'warning');
      return;
    }

    setDataBusy(true);
    try {
      const res = await axios.post(`${API_BASE}/data/export`, payload, { responseType: 'blob' });
      const filename = filenameFromDisposition(res.headers['content-disposition'], `transcripts.${dataExportDraft.format === 'markdown' ? 'md' : dataExportDraft.format}`);
      downloadBlobFile(res.data, filename);
      markApiOnline();
      addLog('Downloaded transcript data export', 'success', payload);
      await fetchDataTables();
      await fetchBackendEvents();
    } catch (error) {
      reportApiError('Failed to export transcript data', error);
    } finally {
      setDataBusy(false);
    }
  };

  const handleExportSelectedCollectionMarkdown = async () => {
    if (!selectedCollectionId) return;

    try {
      const res = await axios.get(`${API_BASE}/collections/${selectedCollectionId}/markdown`, {
        responseType: 'text',
      });
      downloadTextFile(res.data, `collection-${selectedCollectionId}.md`, 'text/markdown');
      addLog('Exported selected collection as Markdown', 'success');
    } catch (error) {
      reportApiError('Failed to export collection Markdown', error);
    }
  };

  const handleExportCollectionsJson = async () => {
    try {
      const res = await axios.get(`${API_BASE}/collections/export`);
      downloadTextFile(JSON.stringify(res.data, null, 2), 'research-collections.json', 'application/json');
      addLog(`Exported ${res.data.collections.length} collections`, 'success');
    } catch (error) {
      reportApiError('Failed to export collections JSON', error);
    }
  };

  const handleImportCollectionsJson = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const parsed = JSON.parse(await file.text());
      const collections = Array.isArray(parsed) ? parsed : parsed.collections;
      if (!Array.isArray(collections)) {
        throw new Error('Expected a collections array');
      }

      const res = await axios.post(`${API_BASE}/collections/import`, {
        collections,
        replace: false,
      });
      setResearchOrg(res.data.organization);
      addLog(`Imported ${res.data.imported_count} collections`, 'success');
    } catch (error) {
      addLog('Failed to import collections JSON', 'error', {
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      event.target.value = '';
    }
  };

  const copyToClipboard = async () => {
    if (!currentTranscript) return;

    try {
      await navigator.clipboard.writeText(currentTranscript.transcript ?? '');
      addLog('Copied transcript to clipboard', 'success');
    } catch {
      addLog('Failed to copy transcript', 'error');
    }
  };

  const downloadMarkdown = () => {
    if (!currentTranscript) return;
    const fetchedLine = currentTranscript.fetched_at ? `\n**Fetched at**: ${currentTranscript.fetched_at}` : '';
    const content = `# ${currentTranscript.title}\n\n**Channel**: ${currentTranscript.channel}\n**ID**: ${currentTranscript.video_id}\n**Uploaded at**: ${getDisplayDateValue(currentTranscript)}${fetchedLine}\n\n---\n\n${currentTranscript.transcript}`;
    downloadTextFile(content, `${currentTranscript.video_id}.md`, 'text/markdown');
  };

  const formatTimestamp = (seconds: number) => {
    const totalSeconds = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };

  const getTimestampUrl = (videoId: string, start: number) => (
    `https://youtube.com/watch?v=${videoId}&t=${Math.max(0, Math.floor(start))}s`
  );

  const formatCompactNumber = (value: number) => (
    new Intl.NumberFormat(undefined, { notation: 'compact' }).format(value)
  );

  const formatDuration = (seconds: number) => {
    const totalMinutes = Math.round(seconds / 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;

    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }

    return `${minutes}m`;
  };

  const saveCurrentSearch = () => {
    const query = searchQuery.trim();
    if (query.length < 2) return;

    setSavedSearches(prev => [query, ...prev.filter(saved => saved.toLowerCase() !== query.toLowerCase())].slice(0, 10));
  };

  const removeSavedSearch = (query: string) => {
    setSavedSearches(prev => prev.filter(saved => saved !== query));
  };

  const renderHighlightedText = (text: string, className?: string, queryOverride = searchQuery) => {
    const terms = getQueryTerms(queryOverride);
    if (terms.length === 0) {
      return <span className={className}>{text}</span>;
    }

    const escapedTerms = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const pattern = new RegExp(`(${escapedTerms.join('|')})`, 'gi');
    const parts = text.split(pattern);

    return (
      <span className={className}>
        {parts.map((part, index) => (
          terms.includes(part.toLowerCase()) ? (
            <mark key={`${part}-${index}`} className="rounded-sm bg-amber-200 px-0.5 text-slate-950">
              {part}
            </mark>
          ) : (
            <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
          )
        ))}
      </span>
    );
  };

  const channels = useMemo(() => (
    Array.from(new Set(transcripts.map(transcript => transcript.channel))).sort()
  ), [transcripts]);

  const selectedCollection = useMemo(() => (
    researchOrg.collections.find(collection => collection.id === selectedCollectionId) ?? null
  ), [researchOrg.collections, selectedCollectionId]);

  const transcriptById = useMemo(() => (
    new Map(transcripts.map(transcript => [transcript.video_id, transcript]))
  ), [transcripts]);

  const getSearchResultRuntime = useCallback((result: SearchResult) => (
    result.runtime_seconds ?? result.duration_seconds ?? getTranscriptRuntime(transcriptById.get(result.video_id))
  ), [transcriptById]);

  const getSearchResultMatchCount = useCallback((result: SearchResult) => (
    result.match_count ?? result.matches?.length ?? countQueryMatches(transcriptById.get(result.video_id)?.transcript ?? '', searchQuery)
  ), [searchQuery, transcriptById]);

  /** Body matches for the current query, resolved by the backend rather than by
   *  scanning every transcript in the browser. */
  const searchResultIds = useMemo(() => (
    new Set(searchResults.map(result => result.video_id))
  ), [searchResults]);

  const matchCountById = useMemo(() => new Map(
    searchResults.map(result => [result.video_id, result.match_count ?? result.matches?.length ?? 0])
  ), [searchResults]);

  const filteredTranscripts = useMemo(() => transcripts.filter(transcript => {
    const query = searchQuery.toLowerCase();
    const matchesChannel = channelFilter === 'all' || transcript.channel === channelFilter;
    const tags = researchOrg.tags[transcript.video_id] ?? [];
    const matchesQuery = !query ||
      transcript.title.toLowerCase().includes(query) ||
      transcript.channel.toLowerCase().includes(query) ||
      tags.some(tag => tag.includes(query)) ||
      searchResultIds.has(transcript.video_id);

    return matchesChannel && matchesQuery;
  }), [channelFilter, researchOrg.tags, searchQuery, searchResultIds, transcripts]);

  const sortedTranscripts = useMemo(() => [...filteredTranscripts].sort((a, b) => {
    const effectiveSort = sortBy === 'relevance' ? 'newest' : sortBy;

    if (effectiveSort === 'title') {
      return a.title.localeCompare(b.title);
    }

    if (effectiveSort === 'longest') {
      return getTranscriptRuntime(b) - getTranscriptRuntime(a);
    }

    if (effectiveSort === 'most_matches') {
      return (matchCountById.get(b.video_id) ?? 0) - (matchCountById.get(a.video_id) ?? 0);
    }

    return parseDisplayDateMillis(getDisplayDateValue(b)) - parseDisplayDateMillis(getDisplayDateValue(a));
  }), [filteredTranscripts, matchCountById, sortBy]);

  const sortedSearchResults = useMemo(() => [...searchResults].sort((a, b) => {
    if (sortBy === 'title') {
      return a.title.localeCompare(b.title);
    }

    if (sortBy === 'longest') {
      return getSearchResultRuntime(b) - getSearchResultRuntime(a);
    }

    if (sortBy === 'most_matches') {
      return getSearchResultMatchCount(b) - getSearchResultMatchCount(a);
    }

    if (sortBy === 'newest') {
      return parseDisplayDateMillis(getDisplayDateValue(b)) - parseDisplayDateMillis(getDisplayDateValue(a));
    }

    return (b.score ?? 0) - (a.score ?? 0);
  }), [getSearchResultMatchCount, getSearchResultRuntime, searchResults, sortBy]);

  const selectedSearchResult = currentTranscript
    ? sortedSearchResults.find(result => result.video_id === currentTranscript.video_id)
    : null;

  const selectedSummary = currentTranscript ? {
    wordCount: selectedSearchResult?.word_count ?? countWords(currentTranscript.transcript ?? ''),
    runtime: selectedSearchResult ? getSearchResultRuntime(selectedSearchResult) : getTranscriptRuntime(currentTranscript),
    segmentCount: selectedSearchResult?.segment_count ?? currentTranscript.segments?.length ?? 0,
    matchCount: selectedSearchResult?.match_count ?? selectedSearchResult?.matches?.length ?? countQueryMatches(currentTranscript.transcript ?? '', searchQuery),
  } : null;

  const currentTags = currentTranscript ? researchOrg.tags[currentTranscript.video_id] ?? [] : [];
  const currentTimestampNotes = currentTranscript ? researchOrg.timestamp_notes[currentTranscript.video_id] ?? [] : [];
  const selectedRunFromList = fetchRuns.find(run => run.id === selectedRunId) ?? null;
  const visibleRun = selectedRun ?? selectedRunFromList;
  const isArchived = Boolean(currentTranscript && archivedIds.includes(currentTranscript.video_id));
  const currentAISummary = currentTranscript ? summaryByVideoId[currentTranscript.video_id] : null;
  const selectedCompareTranscripts = compareVideoIds
    .map(videoId => transcriptById.get(videoId))
    .filter((transcript): transcript is Transcript => Boolean(transcript));
  const latestAIArtifacts = useMemo(() => (
    [...aiArtifacts].sort((a, b) => (
      parseDisplayDateMillis(b.generated_at ?? b.created_at) - parseDisplayDateMillis(a.generated_at ?? a.created_at)
    ))
  ), [aiArtifacts]);
  const healthStatus = (aiHealth?.status ?? '').toLowerCase();
  const aiHealthOk = aiHealth?.ok === true || aiHealth?.success === true || ['ok', 'healthy', 'success'].includes(healthStatus);
  const aiHealthFailed = aiHealth?.ok === false || aiHealth?.success === false || ['error', 'failed', 'unhealthy'].includes(healthStatus);

  const hasSearch = searchQuery.trim().length >= 2;
  const hasSemanticSearch = semanticSearchSubmitted || semanticSearchLoading || semanticResults.length > 0;
  const formatDateTime = formatDisplayDateTime;

  const runStatusClass = (value: string) => {
    if (value === 'success') return 'bg-emerald-50 text-emerald-700';
    if (value === 'partial') return 'bg-amber-50 text-amber-700';
    if (value === 'failed') return 'bg-red-50 text-red-700';
    if (value === 'running') return 'bg-blue-50 text-blue-700';
    return 'bg-slate-100 text-slate-600';
  };

  const renderMetricTile = (label: string, value: React.ReactNode, icon: React.ReactNode, accent = 'text-slate-500') => (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className={`mb-2 flex h-8 w-8 items-center justify-center rounded-md bg-slate-50 ${accent}`}>
        {icon}
      </div>
      <div className="text-lg font-semibold text-slate-950">{value}</div>
      <div className="mt-0.5 text-xs font-medium text-slate-500">{label}</div>
    </div>
  );

  const renderActiveTask = () => {
    if (!status.current_task) return null;

    const hasMeasuredProgress = status.total > 0;
    const percentage = hasMeasuredProgress ? Math.min(100, Math.round((status.progress / status.total) * 100)) : 0;

    return (
      <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="font-semibold text-blue-900">{status.message}</span>
          <span className="font-semibold text-blue-700">{hasMeasuredProgress ? `${percentage}%` : 'Working'}</span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
          <div
            className={`h-full rounded-full bg-blue-600 transition-all duration-500 ${hasMeasuredProgress ? '' : 'animate-pulse'}`}
            style={{ width: hasMeasuredProgress ? `${percentage}%` : '100%' }}
          />
        </div>
      </div>
    );
  };

  const renderFetchBar = () => (
    <section className={`${panelClass} p-4`}>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            placeholder="YouTube video URL"
            className={fieldClass}
            value={videoUrl}
            onChange={(event) => setVideoUrl(event.target.value)}
          />
          <button onClick={handleFetchVideo} disabled={!videoUrl.trim() || fetchRequestBusy || Boolean(status.current_task)} className={`${primaryButtonClass} sm:w-32`}>
            {fetchRequestBusy || status.current_task === 'video' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {fetchRequestBusy || status.current_task === 'video' ? 'Starting' : 'Fetch'}
          </button>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            placeholder="Channel URL"
            className={fieldClass}
            value={channelUrl}
            onChange={(event) => setChannelUrl(event.target.value)}
          />
          <input
            type="number"
            min={1}
            max={500}
            placeholder="30"
            title="How many recent videos to list. Blank walks the whole channel."
            className={`${fieldClass} sm:w-24`}
            value={channelLimit}
            onChange={(event) => setChannelLimit(event.target.value)}
          />
          <button
            onClick={handleToggleFollow}
            disabled={!channelUrl.trim() || followBusy}
            className={`${followingChannel ? primaryButtonClass : secondaryButtonClass} sm:w-32`}
            title={followingChannel ? 'Stop checking this channel for new uploads' : 'Check this channel for new uploads automatically'}
          >
            <Bell className={`h-4 w-4 ${followBusy ? 'animate-pulse' : ''}`} />
            {followingChannel ? 'Following' : 'Follow'}
          </button>
          <button onClick={handlePreviewChannel} disabled={!channelUrl.trim() || channelPreviewBusy} className={`${secondaryButtonClass} sm:w-32`}>
            <ListPlus className={`h-4 w-4 ${channelPreviewBusy ? 'animate-spin' : ''}`} />
            {channelPreviewBusy ? 'Listing' : 'Preview'}
          </button>
          <button onClick={() => handleFetchChannel()} disabled={!channelUrl.trim() || fetchRequestBusy || Boolean(status.current_task)} className={`${secondaryButtonClass} sm:w-32`}>
            <RefreshCw className={`h-4 w-4 ${fetchRequestBusy || status.current_task === 'channel' ? 'animate-spin' : ''}`} />
            {fetchRequestBusy || status.current_task === 'channel' ? 'Starting' : 'Bulk'}
          </button>
        </div>
      </div>
      {renderChannelPreview()}
      <div className="mt-3">{renderActiveTask()}</div>
    </section>
  );

  const renderChannelPreview = () => {
    if (!channelPreview) return null;
    const newSelected = selectedCandidates.length;

    return (
      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-slate-700">
            <span className="font-semibold text-slate-950">{channelPreview.total} listed</span>
            {' · '}
            <span className="text-emerald-700">{channelPreview.new_count} new</span>
            {' · '}
            <span className="text-slate-500">{channelPreview.already_saved_count} already archived</span>
            {' · '}
            <span className="text-slate-400">via {channelPreview.listing_source}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedCandidates(channelPreview.candidates.filter(item => !item.already_saved).map(item => item.video_id))}
              className={secondaryButtonClass}
            >
              Select new
            </button>
            <button
              onClick={() => handleFetchChannel(selectedCandidates)}
              disabled={newSelected === 0 || fetchRequestBusy || Boolean(status.current_task)}
              className={primaryButtonClass}
            >
              <Download className="h-4 w-4" />
              Fetch {newSelected}
            </button>
            <button onClick={() => { setChannelPreview(null); setSelectedCandidates([]); }} className={iconButtonClass} title="Close preview">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto">
          {channelPreview.candidates.map(item => (
            <li key={item.video_id} className="flex items-start gap-2 rounded-md bg-white px-2 py-1.5 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={selectedCandidates.includes(item.video_id)}
                onChange={() => toggleCandidate(item.video_id)}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-slate-800" title={item.title}>{item.title || item.video_id}</div>
                <div className="text-xs text-slate-500">
                  {item.published_text && <span>{item.published_text} · </span>}
                  {item.already_saved
                    ? <span className="text-slate-400">already archived</span>
                    : <span className="text-emerald-700">new</span>}
                </div>
              </div>
              <a href={item.url} target="_blank" rel="noreferrer" className={iconButtonClass} title="Open on YouTube">
                <ExternalLink className="h-4 w-4" />
              </a>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  const renderSearchControls = () => (
    <section className={`${panelClass} p-4`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">Library Search</h2>
        </div>
        <button onClick={saveCurrentSearch} disabled={searchQuery.trim().length < 2} className={iconButtonClass} title="Save search">
          <Bookmark className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search titles, transcripts, tags"
            className={`${fieldClass} pl-9 pr-9`}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              title="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          <label className="block">
            <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-500">
              <Filter className="h-3.5 w-3.5" />
              Channel
            </span>
            <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)} className={fieldClass}>
              <option value="all">All channels</option>
              {channels.map(channel => (
                <option key={channel} value={channel}>{channel}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-500">
              <BarChart3 className="h-3.5 w-3.5" />
              Sort
            </span>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value as SortOption)} className={fieldClass}>
              <option value="relevance">Relevance</option>
              <option value="newest">Newest</option>
              <option value="longest">Longest</option>
              <option value="most_matches">Most matches</option>
              <option value="title">Title</option>
            </select>
          </label>
        </div>

        <form onSubmit={handleSemanticSearch} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <Brain className="h-3.5 w-3.5" />
              Semantic
            </span>
            {(semanticQuery || semanticResults.length > 0) && (
              <button type="button" onClick={clearSemanticSearch} className="text-xs font-semibold text-slate-500 hover:text-slate-900">
                Clear
              </button>
            )}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row xl:flex-col">
            <input
              value={semanticQuery}
              onChange={(event) => setSemanticQuery(event.target.value)}
              placeholder="Find related ideas"
              className={fieldClass}
            />
            <button type="submit" disabled={semanticQuery.trim().length < 2 || semanticSearchLoading} className={secondaryButtonClass}>
              {semanticSearchLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Search
            </button>
          </div>
        </form>
      </div>

      {libraryStats?.top_keywords.length ? (
        <div className="mt-4">
          <div className="mb-2 text-xs font-medium text-slate-500">Top keywords</div>
          <div className="flex flex-wrap gap-1.5">
            {libraryStats.top_keywords.slice(0, 8).map(keyword => (
              <button
                key={keyword.term}
                onClick={() => setSearchQuery(keyword.term)}
                className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                title={`${keyword.count} mentions`}
              >
                {keyword.term}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {savedSearches.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs font-medium text-slate-500">Saved searches</div>
          <div className="flex flex-wrap gap-1.5">
            {savedSearches.map(saved => (
              <span key={saved} className="inline-flex max-w-full items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                <button onClick={() => setSearchQuery(saved)} className="max-w-[11rem] truncate hover:text-blue-700" title={`Search ${saved}`}>
                  {saved}
                </button>
                <button onClick={() => removeSavedSearch(saved)} className="rounded-full p-0.5 text-slate-400 hover:bg-white hover:text-red-600" title="Remove search">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );

  const renderTranscriptList = () => (
    <section className={`${panelClass} overflow-hidden`}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <h2 className="font-semibold text-slate-950">Transcripts</h2>
          <div className="text-xs text-slate-500">{sortedTranscripts.length} shown</div>
        </div>
        <button onClick={fetchTranscripts} className={iconButtonClass} title="Refresh transcripts">
          <RefreshCw className={`h-4 w-4 ${transcriptsLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="max-h-[34rem] overflow-y-auto p-2 xl:max-h-[calc(100vh-25rem)]">
        {sortedTranscripts.map(transcript => (
          <div
            key={transcript.video_id}
            className={`mb-2 rounded-lg border p-3 transition ${
              selectedId === transcript.video_id
                ? 'border-blue-200 bg-blue-50'
                : 'border-slate-200 bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-start gap-2">
              <button onClick={() => handleSelect(transcript.video_id)} className="min-w-0 flex-1 text-left">
                <div className="line-clamp-2 text-sm font-semibold leading-snug text-slate-950">{transcript.title}</div>
                <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                  <User className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{transcript.channel}</span>
                </div>
              </button>
              <button onClick={(event) => handleDelete(transcript.video_id, event)} className={iconButtonClass} title="Delete transcript">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            {(researchOrg.tags[transcript.video_id] ?? []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(researchOrg.tags[transcript.video_id] ?? []).slice(0, 3).map(tag => (
                  <button
                    key={tag}
                    onClick={() => setSearchQuery(tag)}
                    className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-blue-50 hover:text-blue-700"
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {sortedTranscripts.length === 0 && (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            No transcripts match the current filters.
          </div>
        )}
      </div>
    </section>
  );

  const renderStatsPanel = () => {
    if (!libraryStats) return null;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-semibold text-slate-950">Archive</h2>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
            {libraryStats.unique_channels} channels
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {renderMetricTile('Videos', libraryStats.transcript_count, <Youtube className="h-4 w-4" />, 'text-red-600')}
          {renderMetricTile('Words', formatCompactNumber(libraryStats.total_words), <Hash className="h-4 w-4" />, 'text-blue-600')}
          {renderMetricTile('Segments', formatCompactNumber(libraryStats.total_segments), <BarChart3 className="h-4 w-4" />, 'text-emerald-600')}
          {renderMetricTile('Runtime', formatDuration(libraryStats.total_duration_seconds), <Clock className="h-4 w-4" />, 'text-amber-600')}
        </div>
        {libraryStats.channel_counts.length > 0 && (
          <div className="mt-4 space-y-2">
            {libraryStats.channel_counts.slice(0, 4).map(channel => (
              <button
                key={channel.channel}
                onClick={() => setChannelFilter(channel.channel)}
                className="flex w-full items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2 text-left text-sm hover:bg-blue-50"
              >
                <span className="min-w-0 truncate font-medium text-slate-700">{channel.channel}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-500">{channel.count}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  };

  const renderStoragePanel = () => {
    if (!storageStatus) return null;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-slate-500" />
            <h2 className="font-semibold text-slate-950">Storage</h2>
          </div>
          <span className={`rounded-full px-2 py-1 text-xs font-semibold ${
            storageStatus.backend === 'sqlite' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
          }`}>
            {storageStatus.backend}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-sm">
          <div className="rounded-md bg-slate-50 px-3 py-2">
            <div className="font-semibold text-slate-950">{storageStatus.active_count}</div>
            <div className="text-xs text-slate-500">Active</div>
          </div>
          <div className="rounded-md bg-slate-50 px-3 py-2">
            <div className="font-semibold text-slate-950">{storageStatus.json.count}</div>
            <div className="text-xs text-slate-500">JSON</div>
          </div>
          <div className="rounded-md bg-slate-50 px-3 py-2">
            <div className="font-semibold text-slate-950">{storageStatus.sqlite.count}</div>
            <div className="text-xs text-slate-500">{storageStatus.sqlite.fts_enabled ? 'SQLite FTS' : 'SQLite'}</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            onClick={handleMigrateStorage}
            disabled={storageBusy || storageStatus.backend === 'sqlite' || !storageStatus.json.exists}
            className={primaryButtonClass}
          >
            <Database className="h-4 w-4" />
            Migrate
          </button>
          <button onClick={handleExportJson} disabled={storageBusy || storageStatus.active_count === 0} className={secondaryButtonClass}>
            <Download className="h-4 w-4" />
            Backup
          </button>
        </div>
      </section>
    );
  };

  const renderAIOutput = (title: string, artifact: AIArtifact | null) => {
    if (!artifact) return null;

    return (
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="min-w-0 text-sm font-semibold text-slate-950">{title}</div>
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
            {artifact.status || 'saved'}
          </span>
        </div>
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-700">
          {JSON.stringify(artifact.content ?? artifact, null, 2)}
        </pre>
      </div>
    );
  };

  const renderAIWorkspacePanel = () => (
    <section className={`${panelClass} p-4`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">AI Workspace</h2>
        </div>
        <button onClick={fetchEmbeddingStatus} className={iconButtonClass} title="Refresh AI workspace">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-3">
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950">Semantic Index</div>
              <div className="mt-1 text-xs text-slate-500">
                {embeddingStatus ? `${embeddingStatus.chunk_count} chunks, ${embeddingStatus.stale_count} stale` : 'Status not loaded'}
              </div>
            </div>
            <button
              onClick={handleRebuildEmbeddings}
              disabled={!aiSettings.enabled || embeddingBusy || Boolean(status.current_task)}
              className={secondaryButtonClass}
              title={aiSettings.enabled ? 'Rebuild local vector index' : 'Enable AI first'}
            >
              {embeddingBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Rebuild
            </button>
          </div>
          {embeddingStatus?.embedding_model && (
            <div className="mt-2 truncate text-xs font-medium text-slate-500">{embeddingStatus.embedding_model}</div>
          )}
        </div>

        <div className="rounded-lg bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-slate-950">Compare</div>
              <div className="text-xs text-slate-500">{compareVideoIds.length} selected</div>
            </div>
            {compareVideoIds.length > 0 && (
              <button onClick={() => setCompareVideoIds([])} className="text-xs font-semibold text-slate-500 hover:text-slate-900">
                Clear
              </button>
            )}
          </div>

          {selectedCompareTranscripts.length > 0 ? (
            <div className="mb-3 max-h-32 space-y-1 overflow-y-auto">
              {selectedCompareTranscripts.map(transcript => (
                <div key={transcript.video_id} className="flex items-center gap-2 rounded-md bg-white px-2 py-1.5 text-xs">
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-700">{transcript.title}</span>
                  <button onClick={() => toggleCompareVideo(transcript.video_id)} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" title="Remove">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="mb-3 rounded-md bg-white px-3 py-4 text-center text-xs text-slate-500">
              Add videos from the transcript header.
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={handleCompareVideos}
              disabled={!aiSettings.enabled || comparisonBusy || compareVideoIds.length < 2 || Boolean(status.current_task)}
              className={secondaryButtonClass}
            >
              {comparisonBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              Compare
            </button>
            <button
              onClick={handleBuildTimeline}
              disabled={!aiSettings.enabled || timelineBusy || Boolean(status.current_task)}
              className={secondaryButtonClass}
            >
              {timelineBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Clock className="h-4 w-4" />}
              Timeline
            </button>
          </div>
        </div>

        {renderAIOutput('Comparison', comparisonOutput)}
        {renderAIOutput('Timeline', timelineOutput)}
      </div>
    </section>
  );

  const renderCollectionsPanel = () => (
    <section className={`${panelClass} p-4`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FolderPlus className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">Collections</h2>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{researchOrg.collections.length}</span>
      </div>

      <div className="space-y-2">
        <input value={newCollectionName} onChange={(event) => setNewCollectionName(event.target.value)} placeholder="Collection name" className={fieldClass} />
        <input value={newCollectionDescription} onChange={(event) => setNewCollectionDescription(event.target.value)} placeholder="Description" className={fieldClass} />
        <button onClick={handleCreateCollection} disabled={!newCollectionName.trim()} className={`${primaryButtonClass} w-full`}>
          <Plus className="h-4 w-4" />
          Create Collection
        </button>
      </div>

      {researchOrg.collections.length > 0 && (
        <div className="mt-3 space-y-3">
          <select value={selectedCollectionId} onChange={(event) => setSelectedCollectionId(event.target.value)} className={fieldClass}>
            {researchOrg.collections.map(collection => (
              <option key={collection.id} value={collection.id}>{collection.name} ({collection.clips.length})</option>
            ))}
          </select>

          {selectedCollection && (
            <div className="rounded-lg bg-slate-50 p-3">
              <div className="line-clamp-2 font-semibold text-slate-900">{selectedCollection.name}</div>
              {selectedCollection.description && (
                <div className="mt-1 line-clamp-2 text-sm text-slate-500">{selectedCollection.description}</div>
              )}
              <div className="mt-2 text-xs font-medium text-slate-500">{selectedCollection.clips.length} saved clips</div>
              <div className="mt-3 grid grid-cols-4 gap-2">
                <button onClick={handleExportSelectedCollectionMarkdown} className={iconButtonClass} title="Export Markdown">
                  <FileDown className="h-4 w-4" />
                </button>
                <button onClick={handleExportCollectionsJson} className={iconButtonClass} title="Export JSON">
                  <Download className="h-4 w-4" />
                </button>
                <label className={iconButtonClass} title="Import JSON">
                  <FileUp className="h-4 w-4" />
                  <input type="file" accept="application/json,.json" onChange={handleImportCollectionsJson} className="hidden" />
                </label>
                <button onClick={handleDeleteCollection} className={iconButtonClass} title="Delete collection">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );

  const renderActivityPanel = () => (
    <section className={`${panelClass} overflow-hidden`}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">Activity</h2>
        </div>
        <button onClick={() => setLogs([])} className="text-sm font-medium text-slate-500 hover:text-slate-900">Clear</button>
      </div>
      <div className="max-h-72 overflow-y-auto p-3">
        {logs.slice(0, 12).map(log => (
          <details
            key={log.id}
            className={`mb-2 rounded-md px-3 py-2 text-sm ${
              log.type === 'error' ? 'bg-red-50 text-red-700' :
              log.type === 'warning' ? 'bg-amber-50 text-amber-700' :
              log.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-50 text-slate-700'
            }`}
          >
            <summary className="flex cursor-pointer list-none items-start gap-2">
              <span className="shrink-0 text-xs opacity-70">{log.time}</span>
              <span className="min-w-0 flex-1 break-words font-medium">
                <span className="mr-2 rounded bg-white/70 px-1.5 py-0.5 text-[0.65rem] uppercase opacity-70">
                  {log.source}{log.event ? `:${log.event}` : ''}
                </span>
                {log.msg}
              </span>
            </summary>
            {log.details && Object.keys(log.details).length > 0 && (
              <pre className="mt-2 max-h-24 overflow-auto rounded-md bg-white/80 p-2 text-xs text-slate-600">
                {JSON.stringify(log.details, null, 2)}
              </pre>
            )}
          </details>
        ))}
        {logs.length === 0 && (
          <div className="rounded-md bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">No activity yet.</div>
        )}
      </div>
    </section>
  );

  const renderSemanticResults = () => {
    if (!hasSemanticSearch) return null;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-950">Semantic Results</h2>
            <div className="text-sm text-slate-500">
              {semanticSearchLoading ? 'Searching by meaning...' : `${semanticResults.length} related videos`}
            </div>
          </div>
          <Brain className="h-5 w-5 text-slate-400" />
        </div>

        {semanticSearchLoading ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">Searching semantic index...</div>
        ) : semanticResults.length === 0 ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No semantic matches for this query.</div>
        ) : (
          <div className="space-y-3">
            {semanticResults.map((result, index) => {
              const transcript = transcriptById.get(result.video_id);
              const title = result.title || transcript?.title || result.video_id || 'Untitled video';
              const channel = result.channel || transcript?.channel || 'Unknown channel';
              const excerpt = result.excerpt || result.matches[0]?.text || transcript?.transcript?.slice(0, 280) || '';
              const score = result.semantic_score ?? result.similarity ?? result.score;

              return (
                <article key={`${result.video_id || 'semantic'}-${index}`} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <button onClick={() => handleSelect(result.video_id)} disabled={!result.video_id} className="min-w-0 text-left disabled:cursor-not-allowed disabled:opacity-60">
                      <h3 className="line-clamp-2 font-semibold leading-snug text-slate-950 hover:text-blue-700">{title}</h3>
                      <div className="mt-1 text-sm text-slate-500">{channel}</div>
                    </button>
                    {typeof score === 'number' && (
                      <div className="shrink-0 rounded-md bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">
                        {score.toFixed(score <= 1 ? 2 : 0)}
                      </div>
                    )}
                  </div>
                  {excerpt && (
                    <p className="mt-3 text-sm leading-6 text-slate-700">
                      {renderHighlightedText(excerpt, undefined, semanticQuery)}
                    </p>
                  )}
                  {result.reason && (
                    <div className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-xs font-medium text-slate-600">{result.reason}</div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    );
  };

  const renderAISummaryPanel = () => {
    if (!currentTranscript) return null;

    const isLoading = summaryLoadingId === currentTranscript.video_id;
    const isGenerating = summaryGeneratingId === currentTranscript.video_id;
    const generationDisabled = aiSettingsLoaded && !aiSettings.enabled;

    return (
      <section className={`${panelClass} p-4 sm:p-5`}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-blue-600" />
              <h2 className="font-semibold text-slate-950">AI Summary</h2>
            </div>
            <div className="mt-1 text-sm text-slate-500">
              {currentAISummary?.generated_at ? `Generated ${formatDateTime(currentAISummary.generated_at)}` : 'Concise summary, claims, entities, and suggested tags'}
            </div>
          </div>
          <button
            onClick={handleGenerateSummary}
            disabled={isLoading || isGenerating || generationDisabled}
            className={primaryButtonClass}
            title={generationDisabled ? 'Enable AI in Settings first' : currentAISummary ? 'Refresh summary' : 'Generate summary'}
          >
            {isGenerating ? <RefreshCw className="h-4 w-4 animate-spin" /> : <WandSparkles className="h-4 w-4" />}
            {isGenerating ? 'Generating' : currentAISummary ? 'Refresh' : 'Generate'}
          </button>
        </div>

        {isLoading ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">Loading saved summary...</div>
        ) : generationDisabled ? (
          <div className="rounded-lg bg-amber-50 px-4 py-4 text-sm font-medium text-amber-700">AI is disabled in Settings.</div>
        ) : !currentAISummary ? (
          <div className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">No AI summary saved for this transcript.</div>
        ) : (
          <div className="space-y-4">
            {currentAISummary.text && (
              <p className="rounded-lg bg-blue-50 px-4 py-3 text-sm leading-6 text-slate-800">{currentAISummary.text}</p>
            )}

            {currentAISummary.key_claims.length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <FileText className="h-4 w-4 text-slate-500" />
                  Key Claims
                </div>
                <div className="space-y-2">
                  {currentAISummary.key_claims.map((claim, index) => (
                    <div key={`${claim}-${index}`} className="rounded-md bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">{claim}</div>
                  ))}
                </div>
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-2">
              {currentAISummary.entities.length > 0 && (
                <div>
                  <div className="mb-2 text-sm font-semibold text-slate-900">Entities</div>
                  <div className="flex flex-wrap gap-1.5">
                    {currentAISummary.entities.map(entity => (
                      <span key={entity} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">{entity}</span>
                    ))}
                  </div>
                </div>
              )}

              {currentAISummary.suggested_tags.length > 0 && (
                <div>
                  <div className="mb-2 text-sm font-semibold text-slate-900">Suggested Tags</div>
                  <div className="flex flex-wrap gap-1.5">
                    {currentAISummary.suggested_tags.map(tag => (
                      <button key={tag} onClick={() => setSearchQuery(tag)} className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-100">
                        #{tag}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {currentAISummary.warnings.length > 0 && (
              <div className="rounded-lg bg-amber-50 p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-800">
                  <AlertTriangle className="h-4 w-4" />
                  Warnings
                </div>
                <div className="space-y-1 text-sm text-amber-700">
                  {currentAISummary.warnings.map((warning, index) => (
                    <div key={`${warning}-${index}`}>{warning}</div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-2 text-xs font-medium text-slate-500">
              {currentAISummary.provider && <span className="rounded-full bg-slate-100 px-2 py-1">{currentAISummary.provider}</span>}
              {currentAISummary.model && <span className="rounded-full bg-slate-100 px-2 py-1">{currentAISummary.model}</span>}
              {currentAISummary.prompt_version && <span className="rounded-full bg-slate-100 px-2 py-1">Prompt {currentAISummary.prompt_version}</span>}
              {currentAISummary.status && <span className="rounded-full bg-slate-100 px-2 py-1">{currentAISummary.status}</span>}
              {currentAISummary.stale && <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700">Stale</span>}
            </div>
          </div>
        )}
      </section>
    );
  };

  const renderMatchedMoments = (results: SearchResult[], title: string) => {
    if (!hasSearch) return null;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-950">{title}</h2>
            <div className="text-sm text-slate-500">{searchLoading ? 'Searching...' : `${results.length} videos matched`}</div>
          </div>
          <Search className="h-5 w-5 text-slate-400" />
        </div>

        {searchLoading ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">Searching transcripts...</div>
        ) : results.length === 0 ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No matched moments for this search.</div>
        ) : (
          <div className="space-y-3">
            {results.map(result => (
              <article key={result.video_id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <button onClick={() => handleSelect(result.video_id)} className="min-w-0 text-left">
                    <h3 className="line-clamp-2 font-semibold leading-snug text-slate-950 hover:text-blue-700">{result.title}</h3>
                    <div className="mt-1 text-sm text-slate-500">{result.channel}</div>
                  </button>
                  <div className="shrink-0 rounded-md bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600">
                    {getSearchResultMatchCount(result)} matches
                  </div>
                </div>

                {result.matches.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {result.matches.map(match => (
                      <div key={`${result.video_id}-${match.start}-${match.text}`} className="flex items-start gap-2 rounded-md bg-slate-50 p-2">
                        <a
                          href={getTimestampUrl(result.video_id, match.start)}
                          target="_blank"
                          rel="noreferrer"
                          className="shrink-0 rounded-md bg-white px-2 py-1 font-mono text-xs font-semibold text-blue-700 hover:text-blue-900"
                          title={`Open YouTube at ${formatTimestamp(match.start)}`}
                        >
                          {formatTimestamp(match.start)}
                        </a>
                        <div className="min-w-0 flex-1 text-sm leading-relaxed text-slate-700">
                          {renderHighlightedText(match.text)}
                        </div>
                        <button
                          onClick={() => handleSaveClip(result.video_id, match.start, match.text, match.start + match.duration)}
                          disabled={!selectedCollectionId}
                          className={iconButtonClass}
                          title={selectedCollectionId ? 'Save clip' : 'Select a collection first'}
                        >
                          <ListPlus className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    );
  };

  const renderTranscriptDetail = () => {
    if (loading) {
      return (
        <section className={`${panelClass} flex min-h-[28rem] items-center justify-center p-8`}>
          <div className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Loading transcript
          </div>
        </section>
      );
    }

    if (!currentTranscript) {
      if (hasSemanticSearch) {
        return renderSemanticResults();
      }

      if (hasSearch) {
        return renderMatchedMoments(sortedSearchResults, 'Search Results');
      }

      return (
        <section className={`${panelClass} flex min-h-[28rem] items-center justify-center p-8`}>
          <div className="text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-lg bg-slate-100 text-slate-400">
              <Youtube className="h-8 w-8" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-slate-950">Select a transcript</h2>
            <p className="mt-1 text-sm text-slate-500">Saved videos, search matches, notes, and clips appear here.</p>
          </div>
        </section>
      );
    }

    return (
      <div className="space-y-4">
        <section className={`${panelClass} p-4 sm:p-5`}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold leading-tight text-slate-950 sm:text-2xl">{currentTranscript.title}</h1>
              <div className="mt-3 flex flex-wrap gap-2 text-sm text-slate-600">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1">
                  <User className="h-4 w-4" />
                  {currentTranscript.channel}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1">
                  <Calendar className="h-4 w-4" />
                  Uploaded {formatDisplayDateTime(getDisplayDateValue(currentTranscript))}
                </span>
                <a
                  href={`https://youtube.com/watch?v=${currentTranscript.video_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 font-medium text-blue-700 hover:bg-blue-100"
                >
                  <ExternalLink className="h-4 w-4" />
                  YouTube
                </a>
                {downloaderUrl && (
                  <a
                    href={`${downloaderUrl}/?url=${encodeURIComponent(currentTranscript.source_url || `https://www.youtube.com/watch?v=${currentTranscript.video_id}`)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700 hover:bg-slate-200"
                    title="Open this video in the downloader app"
                  >
                    <Download className="h-4 w-4" />
                    Download
                  </a>
                )}
                {archiveStorage?.available && (
                  isArchived ? (
                    <>
                      <button
                        onClick={() => setPlayingOffline(value => !value)}
                        className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 font-medium text-emerald-800 hover:bg-emerald-100"
                        title="Play the stored copy, no internet needed"
                      >
                        <Play className="h-4 w-4" />
                        {playingOffline ? 'Hide player' : 'Play offline'}
                      </button>
                      <button
                        onClick={handleDeleteArchived}
                        className={iconButtonClass}
                        title="Delete the stored video file, keep the transcript"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={handleArchiveVideo}
                      disabled={archiveBusy || Boolean(status.current_task)}
                      className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                      title="Keep a copy of the video, so it survives being taken down"
                    >
                      <Save className="h-4 w-4" />
                      {status.current_task === 'archive' ? 'Saving' : 'Keep offline'}
                    </button>
                  )
                )}
                {speechAvailable && (
                  <button
                    onClick={handleTranscribeBySpeech}
                    disabled={fetchRequestBusy || Boolean(status.current_task)}
                    className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    title="Transcribe from the audio instead of the captions, with speaker labels"
                  >
                    <WandSparkles className="h-4 w-4" />
                    {status.current_task === 'speech' ? 'Transcribing' : 'Re-transcribe'}
                  </button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:flex sm:shrink-0">
              <button
                onClick={() => toggleCompareVideo(currentTranscript.video_id)}
                className={secondaryButtonClass}
                title={compareVideoIds.includes(currentTranscript.video_id) ? 'Remove from comparison' : 'Add to comparison'}
              >
                <ListPlus className="h-4 w-4" />
                {compareVideoIds.includes(currentTranscript.video_id) ? 'Added' : 'Compare'}
              </button>
              <button onClick={copyToClipboard} className={secondaryButtonClass}>
                <Copy className="h-4 w-4" />
                Copy
              </button>
              <button onClick={downloadMarkdown} className={secondaryButtonClass}>
                <Download className="h-4 w-4" />
                Markdown
              </button>
            </div>
          </div>

          {selectedSummary && (
            <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
              {renderMetricTile('Words', formatCompactNumber(selectedSummary.wordCount), <Hash className="h-4 w-4" />, 'text-blue-600')}
              {renderMetricTile('Runtime', formatDuration(selectedSummary.runtime), <Clock className="h-4 w-4" />, 'text-amber-600')}
              {renderMetricTile('Segments', formatCompactNumber(selectedSummary.segmentCount), <BarChart3 className="h-4 w-4" />, 'text-emerald-600')}
              {renderMetricTile('Matches', formatCompactNumber(selectedSummary.matchCount), <Search className="h-4 w-4" />, 'text-purple-600')}
            </div>
          )}
        </section>

        {renderAISummaryPanel()}

        <section className={`${panelClass} p-4 sm:p-5`}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Tag className="h-4 w-4 text-slate-500" />
                Tags
              </div>
              <div className="mb-3 flex min-h-7 flex-wrap gap-1.5">
                {currentTags.length > 0 ? currentTags.map(tag => (
                  <button key={tag} onClick={() => setSearchQuery(tag)} className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100">
                    #{tag}
                  </button>
                )) : (
                  <span className="text-sm text-slate-500">No tags saved.</span>
                )}
              </div>
              <div className="flex gap-2">
                <input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="agent, strategy, tools" className={fieldClass} />
                <button onClick={handleSaveTags} className={iconButtonClass} title="Save tags">
                  <Save className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                <MessageSquare className="h-4 w-4 text-slate-500" />
                Video Note
              </div>
              <textarea
                value={videoNoteDraft}
                onChange={(event) => setVideoNoteDraft(event.target.value)}
                rows={4}
                placeholder="Source notes"
                className={`${fieldClass} resize-none`}
              />
              <button onClick={handleSaveVideoNote} className={`${secondaryButtonClass} mt-2`}>
                <Save className="h-4 w-4" />
                Save Note
              </button>
            </div>
          </div>

          {selectedCollection && (
            <div className="mt-4 rounded-lg bg-slate-50 p-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-medium text-slate-500">Selected collection</div>
                  <div className="font-semibold text-slate-950">{selectedCollection.name}</div>
                </div>
                <button onClick={() => handleSaveClip(currentTranscript.video_id, 0, currentTranscript.title, getTranscriptRuntime(currentTranscript))} className={secondaryButtonClass}>
                  <ListPlus className="h-4 w-4" />
                  Save Source
                </button>
              </div>
              {selectedCollection.clips.length > 0 && (
                <div className="mt-3 max-h-40 space-y-2 overflow-y-auto">
                  {selectedCollection.clips.slice(0, 6).map(clip => {
                    const clipTranscript = transcriptById.get(clip.video_id);
                    return (
                      <div key={clip.id} className="flex items-center gap-2 rounded-md bg-white px-3 py-2 text-sm">
                        <span className="w-16 shrink-0 font-mono text-xs font-semibold text-blue-700">{formatTimestamp(clip.start)}</span>
                        <span className="min-w-0 flex-1 truncate text-slate-700">{clipTranscript?.title ?? clip.video_id}</span>
                        <button onClick={() => handleDeleteClip(clip.id)} className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" title="Remove clip">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </section>

        {selectedSearchResult && renderMatchedMoments([selectedSearchResult], 'Matched Moments')}

        <section className={`${panelClass} p-4 sm:p-5`}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-950">Transcript</h2>
              <div className="text-sm text-slate-500">{currentTranscript.segments?.length ?? 0} segments</div>
            </div>
            <button
              onClick={() => setTranscriptCollapsed(prev => !prev)}
              className={secondaryButtonClass}
              title={transcriptCollapsed ? 'Expand transcript' : 'Collapse transcript'}
            >
              {transcriptCollapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
              {transcriptCollapsed ? 'Expand' : 'Collapse'}
            </button>
          </div>

          {transcriptCollapsed ? (
            <div className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm font-medium text-slate-600">
              Transcript collapsed.
            </div>
          ) : (
            <>
              {currentTimestampNotes.length > 0 && (
                <div className="mb-4 rounded-lg bg-slate-50 p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <MessageSquare className="h-4 w-4 text-slate-500" />
                    Timestamp Notes
                  </div>
                  <div className="space-y-2">
                    {currentTimestampNotes.map(note => (
                      <div key={note.id} className="flex items-start gap-2 rounded-md bg-white px-3 py-2 text-sm">
                        <a href={getTimestampUrl(currentTranscript.video_id, note.start)} target="_blank" rel="noreferrer" className="w-16 shrink-0 font-mono text-xs font-semibold text-blue-700">
                          {formatTimestamp(note.start)}
                        </a>
                        <span className="min-w-0 flex-1 text-slate-700">{note.text}</span>
                        <button onClick={() => handleDeleteTimestampNote(note)} className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" title="Delete timestamp note">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-3">
                {(currentTranscript.segments?.length ?? 0) > 0 ? (currentTranscript.segments ?? []).map((segment, index) => {
                  const draftKey = `${segment.start}`;
                  return (
                    <div key={`${segment.start}-${index}`} className="rounded-lg border border-slate-200 p-3">
                      <div className="flex items-start gap-3">
                        <a
                          href={getTimestampUrl(currentTranscript.video_id, segment.start)}
                          target="_blank"
                          rel="noreferrer"
                          title={`Open YouTube at ${formatTimestamp(segment.start)}`}
                          className="w-16 shrink-0 rounded-md bg-slate-50 px-2 py-1 text-center font-mono text-xs font-semibold text-blue-700 hover:bg-blue-50"
                        >
                          {formatTimestamp(segment.start)}
                        </a>
                        <p className="min-w-0 flex-1 text-sm leading-7 text-slate-750">
                          {renderHighlightedText(segment.text)}
                        </p>
                      </div>
                      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                        <input
                          value={timestampNoteDrafts[draftKey] ?? ''}
                          onChange={(event) => setTimestampNoteDrafts(prev => ({ ...prev, [draftKey]: event.target.value }))}
                          placeholder="Timestamp note"
                          className={fieldClass}
                        />
                        <button onClick={() => handleAddTimestampNote(segment)} disabled={!(timestampNoteDrafts[draftKey] ?? '').trim()} className={iconButtonClass} title="Save timestamp note">
                          <MessageSquare className="h-4 w-4" />
                        </button>
                        <button onClick={() => handleSaveClip(currentTranscript.video_id, segment.start, segment.text, segment.start + segment.duration)} disabled={!selectedCollectionId} className={secondaryButtonClass} title={selectedCollectionId ? 'Save clip' : 'Select a collection first'}>
                          <ListPlus className="h-4 w-4" />
                          Clip
                        </button>
                      </div>
                    </div>
                  );
                }) : (
                  <p className="whitespace-pre-wrap text-base leading-7 text-slate-700">{renderHighlightedText(currentTranscript.transcript ?? '')}</p>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    );
  };

  const renderLibraryView = () => (
    <div className="space-y-4">
      {renderFetchBar()}
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_340px]">
        <aside className="space-y-4">
          {renderSearchControls()}
          {renderTranscriptList()}
        </aside>
        <section className="min-w-0 space-y-4">
          {currentTranscript && isArchived && playingOffline && (
          <section className={`${panelClass} overflow-hidden`}>
            <video
              key={currentTranscript.video_id}
              controls
              preload="metadata"
              className="w-full bg-black"
              src={`${API_BASE}/archive/${currentTranscript.video_id}/file`}
            />
            <div className="px-4 py-2 text-xs text-slate-500">
              Playing the stored copy. Seeking works; nothing is requested from YouTube.
            </div>
          </section>
        )}
        {currentTranscript && renderSemanticResults()}
          {renderTranscriptDetail()}
        </section>
        <aside className="space-y-4">
          {renderAIWorkspacePanel()}
          {renderStatsPanel()}
          {renderStoragePanel()}
          {renderCollectionsPanel()}
          {renderActivityPanel()}
        </aside>
      </div>
    </div>
  );

  const renderAISettingsPanel = () => {
    const summaryModelOptions = aiModels.summary.length > 0 ? aiModels.summary : aiModels.all;
    const embeddingModelOptions = aiModels.embedding.length > 0 ? aiModels.embedding : aiModels.all;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-slate-500" />
              <h2 className="font-semibold text-slate-950">AI Models</h2>
            </div>
            <div className="mt-1 text-sm text-slate-500">
              {aiSettingsLoaded ? `${aiSettings.provider || 'Provider not set'} configuration loaded` : 'Connect the local model provider'}
            </div>
          </div>
          <button
            onClick={() => setAISettingsDraft(prev => ({ ...prev, enabled: !prev.enabled }))}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ${
              aiSettingsDraft.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
            }`}
            title="Toggle AI features"
          >
            {aiSettingsDraft.enabled ? <CheckCircle2 className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
            {aiSettingsDraft.enabled ? 'Enabled' : 'Disabled'}
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Provider
            <input
              value={aiSettingsDraft.provider}
              onChange={(event) => setAISettingsDraft(prev => ({ ...prev, provider: event.target.value }))}
              placeholder="Provider name"
              className={`${fieldClass} mt-1`}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Base URL
            <input
              value={aiSettingsDraft.baseUrl}
              onChange={(event) => setAISettingsDraft(prev => ({ ...prev, baseUrl: event.target.value }))}
              placeholder="http://localhost:11434"
              className={`${fieldClass} mt-1`}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Summary model
            <input
              list="ai-summary-model-options"
              value={aiSettingsDraft.summaryModel}
              onChange={(event) => setAISettingsDraft(prev => ({ ...prev, summaryModel: event.target.value }))}
              placeholder="Model from provider"
              className={`${fieldClass} mt-1`}
            />
            <datalist id="ai-summary-model-options">
              {summaryModelOptions.map(model => <option key={model} value={model} />)}
            </datalist>
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Embedding model
            <input
              list="ai-embedding-model-options"
              value={aiSettingsDraft.embeddingModel}
              onChange={(event) => setAISettingsDraft(prev => ({ ...prev, embeddingModel: event.target.value }))}
              placeholder="Model from provider"
              className={`${fieldClass} mt-1`}
            />
            <datalist id="ai-embedding-model-options">
              {embeddingModelOptions.map(model => <option key={model} value={model} />)}
            </datalist>
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Timeout seconds
            <input
              type="number"
              min={1}
              value={aiSettingsDraft.timeoutSeconds}
              onChange={(event) => setAISettingsDraft(prev => ({ ...prev, timeoutSeconds: event.target.value }))}
              className={`${fieldClass} mt-1`}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Temperature
            <div className="mt-1 flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={Number.parseFloat(aiSettingsDraft.temperature) || 0}
                onChange={(event) => setAISettingsDraft(prev => ({ ...prev, temperature: event.target.value }))}
                className="w-full accent-blue-600"
              />
              <input
                type="number"
                min={0}
                max={2}
                step={0.05}
                value={aiSettingsDraft.temperature}
                onChange={(event) => setAISettingsDraft(prev => ({ ...prev, temperature: event.target.value }))}
                className={`${fieldClass} w-24`}
              />
            </div>
          </label>
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <button onClick={fetchAIModels} disabled={aiModelsLoading} className={secondaryButtonClass}>
            <RefreshCw className={`h-4 w-4 ${aiModelsLoading ? 'animate-spin' : ''}`} />
            Models
          </button>
          <button onClick={handleTestAIConnection} disabled={aiHealthLoading} className={secondaryButtonClass}>
            <Plug className="h-4 w-4" />
            Test
          </button>
          <button onClick={handleSaveAISettings} disabled={aiSettingsBusy} className={primaryButtonClass}>
            <Save className="h-4 w-4" />
            Save
          </button>
        </div>

        {aiHealth && (
          <div className={`mt-4 rounded-lg px-3 py-2 text-sm ${
            aiHealthOk ? 'bg-emerald-50 text-emerald-700' :
            aiHealthFailed ? 'bg-red-50 text-red-700' : 'bg-slate-50 text-slate-600'
          }`}>
            <div className="flex items-center gap-2 font-semibold">
              {aiHealthOk ? <CheckCircle2 className="h-4 w-4" /> : aiHealthFailed ? <AlertTriangle className="h-4 w-4" /> : <Cpu className="h-4 w-4" />}
              {aiHealth.message || aiHealth.status || 'AI health checked'}
            </div>
            <div className="mt-1 text-xs opacity-80">
              {[aiHealth.provider, aiHealth.model, typeof aiHealth.latency_ms === 'number' ? `${Math.round(aiHealth.latency_ms)} ms` : ''].filter(Boolean).join(' - ')}
            </div>
          </div>
        )}
      </section>
    );
  };

  const renderAIArtifactsPanel = () => (
    <section className={`${panelClass} overflow-hidden`}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">AI Artifacts</h2>
        </div>
        <button onClick={fetchAIArtifacts} className={iconButtonClass} title="Refresh AI artifacts">
          <RefreshCw className={`h-4 w-4 ${aiArtifactsLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="max-h-[28rem] overflow-y-auto p-3">
        {latestAIArtifacts.length > 0 ? (
          <div className="space-y-2">
            {latestAIArtifacts.slice(0, 10).map((artifact, index) => {
              const transcript = artifact.video_id ? transcriptById.get(artifact.video_id) : null;
              const title = artifact.title || transcript?.title || artifact.video_id || artifact.id || 'Untitled artifact';
              const date = artifact.generated_at || artifact.created_at;

              return (
                <div key={artifact.id || `${artifact.video_id}-${index}`} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-950">{title}</div>
                      <div className="mt-1 text-xs text-slate-500">{artifact.kind || artifact.type || 'artifact'}{date ? ` - ${formatDateTime(date)}` : ''}</div>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${
                      artifact.status === 'failed' ? 'bg-red-50 text-red-700' :
                      artifact.stale ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'
                    }`}>
                      {artifact.stale ? 'stale' : artifact.status || 'saved'}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-xs font-medium text-slate-500">
                    {artifact.provider && <span className="rounded-full bg-slate-50 px-2 py-1">{artifact.provider}</span>}
                    {artifact.model && <span className="rounded-full bg-slate-50 px-2 py-1">{artifact.model}</span>}
                    {artifact.prompt_version && <span className="rounded-full bg-slate-50 px-2 py-1">Prompt {artifact.prompt_version}</span>}
                  </div>
                  {artifact.error && <div className="mt-2 text-xs text-red-600">{artifact.error}</div>}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            {aiArtifactsLoading ? 'Loading AI artifacts...' : 'Generated summaries and embeddings will appear here.'}
          </div>
        )}
      </div>
    </section>
  );

  const renderCurrentTaskPanel = () => (
    <section className={`${panelClass} p-4`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-slate-950">Current Task</h2>
          <div className="text-sm text-slate-500">{status.message}</div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
          status.current_task ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {status.current_task ?? 'Idle'}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {renderMetricTile('Total', status.total ?? 0, <BarChart3 className="h-4 w-4" />)}
        {renderMetricTile('Saved', status.success_count ?? 0, <CheckCircle2 className="h-4 w-4" />, 'text-emerald-600')}
        {renderMetricTile('Failed', status.failure_count ?? 0, <AlertTriangle className="h-4 w-4" />, 'text-red-600')}
        {renderMetricTile('Skipped', status.skipped_count ?? 0, <RotateCcw className="h-4 w-4" />, 'text-amber-600')}
      </div>
      <div className="mt-4">{renderActiveTask()}</div>
      {status.current_task && (
        <button onClick={handleCancelTask} disabled={systemBusy} className={`${secondaryButtonClass} mt-4`}>
          <X className="h-4 w-4" />
          Cancel Task
        </button>
      )}
    </section>
  );

  const renderWatcherPanel = () => {
    const draftChannels = parseSettingsLines(settingsDraft.channelsText);
    const savedChannelCount = watcherSettings.channels.length;

    return (
      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-950">Watched Channels</h2>
            <div className="text-sm text-slate-500">Last check: {formatDateTime(watcherSettings.last_checked_at)}</div>
          </div>
          <button
            onClick={() => setSettingsDraft(prev => ({ ...prev, enabled: !prev.enabled }))}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ${
              settingsDraft.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
            }`}
            title="Toggle watcher"
          >
            {settingsDraft.enabled ? <CheckCircle2 className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
            {settingsDraft.enabled ? 'Enabled' : 'Paused'}
          </button>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={newWatcherChannel}
            onChange={(event) => setNewWatcherChannel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleAddWatcherChannel();
              }
            }}
            placeholder="YouTube channel URL or @handle"
            className={fieldClass}
          />
          <button onClick={handleAddWatcherChannel} disabled={!newWatcherChannel.trim()} className={secondaryButtonClass}>
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>

        <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
          {draftChannels.map(channel => (
            <div key={channel} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-slate-950">{channel}</div>
                <div className="text-xs text-slate-500">{channel.includes('/channel/') ? 'Channel ID URL' : channel.includes('@') ? 'Handle or custom URL' : 'Channel source'}</div>
              </div>
              <button onClick={() => handleRemoveWatcherChannel(channel)} className={iconButtonClass} title="Remove channel">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
          {draftChannels.length === 0 && (
            <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No watched channels configured.</div>
          )}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Frequency minutes
            <input
              type="number"
              min={15}
              value={settingsDraft.frequencyMinutes}
              onChange={(event) => setSettingsDraft(prev => ({ ...prev, frequencyMinutes: event.target.value }))}
              className={`${fieldClass} mt-1`}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Languages
            <input
              value={settingsDraft.languagesText}
              onChange={(event) => setSettingsDraft(prev => ({ ...prev, languagesText: event.target.value }))}
              placeholder="en, es"
              className={`${fieldClass} mt-1`}
            />
          </label>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm text-slate-500">
            {savedChannelCount} saved channels. Next check: {formatDateTime(watcherSettings.next_check_at)}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button onClick={handleSaveWatcherSettings} disabled={settingsBusy} className={primaryButtonClass}>
              <Save className="h-4 w-4" />
              Save
            </button>
            <button onClick={handleRunWatcherNow} disabled={settingsBusy || savedChannelCount === 0 || Boolean(status.current_task)} className={secondaryButtonClass}>
              <Play className="h-4 w-4" />
              Run Now
            </button>
          </div>
        </div>
      </section>
    );
  };

  const renderRunHistoryPanel = () => (
    <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
      <section className={`${panelClass} overflow-hidden`}>
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <h2 className="font-semibold text-slate-950">Run History</h2>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{fetchRuns.length}</span>
        </div>
        <div className="max-h-[32rem] overflow-y-auto p-2">
          {fetchRuns.map(run => (
            <button
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              className={`mb-2 w-full rounded-lg border p-3 text-left transition ${
                selectedRunId === run.id ? 'border-blue-200 bg-blue-50' : 'border-slate-200 bg-white hover:border-slate-300'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950">{run.type} - {run.source}</div>
                  <div className="mt-1 text-xs text-slate-500">{formatDateTime(run.started_at)}</div>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${runStatusClass(run.status)}`}>
                  {run.status}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-4 gap-1 text-center text-xs text-slate-500">
                <span>{run.total} total</span>
                <span>{run.success_count} saved</span>
                <span>{run.failure_count} failed</span>
                <span>{run.skipped_count} skipped</span>
              </div>
            </button>
          ))}
          {fetchRuns.length === 0 && (
            <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No fetch runs recorded yet.</div>
          )}
        </div>
      </section>

      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-semibold text-slate-950">Run Details</h2>
            <div className="text-sm text-slate-500">
              {visibleRun ? `${visibleRun.type} started ${formatDateTime(visibleRun.started_at)}` : 'Select a run to inspect failures.'}
            </div>
          </div>
          {visibleRun && (
            <button
              onClick={() => handleRetryFailedRun(visibleRun.id)}
              disabled={retryingRunId === visibleRun.id || visibleRun.failure_count === 0 || Boolean(status.current_task)}
              className={primaryButtonClass}
              title={visibleRun.failure_count ? 'Retry failed videos' : 'No failed videos to retry'}
            >
              <RotateCcw className="h-4 w-4" />
              Retry Failed
            </button>
          )}
        </div>

        {runLoading ? (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">Loading run details...</div>
        ) : visibleRun ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {renderMetricTile('Saved', visibleRun.success_count, <CheckCircle2 className="h-4 w-4" />, 'text-emerald-600')}
              {renderMetricTile('Failed', visibleRun.failure_count, <AlertTriangle className="h-4 w-4" />, 'text-red-600')}
              {renderMetricTile('Skipped', visibleRun.skipped_count, <RotateCcw className="h-4 w-4" />, 'text-amber-600')}
              {renderMetricTile('Total', visibleRun.total, <BarChart3 className="h-4 w-4" />)}
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              <div className="font-medium text-slate-950">{visibleRun.message || 'No message'}</div>
              <div className="mt-1 text-slate-500">Finished: {formatDateTime(visibleRun.finished_at)}</div>
              <div className="mt-1 truncate text-slate-500">Source: {visibleRun.source}</div>
            </div>

            {visibleRun.failures.length > 0 ? (
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-700">
                  <AlertTriangle className="h-4 w-4" />
                  Failures
                </div>
                <div className="max-h-96 space-y-2 overflow-y-auto">
                  {visibleRun.failures.map((failure, index) => (
                    <div key={`${failure.video_id ?? failure.url ?? 'failure'}-${index}`} className="rounded-lg border border-red-100 bg-red-50 px-3 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-slate-950">{failure.title || failure.video_id || failure.url || 'Unknown video'}</div>
                          <div className="mt-1 text-sm text-red-700">{failure.error || 'Unknown error'}</div>
                        </div>
                        {failure.url && (
                          <a href={failure.url} target="_blank" rel="noreferrer" className={iconButtonClass} title="Open source video">
                            <ExternalLink className="h-4 w-4" />
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg bg-emerald-50 px-4 py-8 text-center text-sm font-medium text-emerald-700">
                No failures recorded for this run.
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">Run details will appear here.</div>
        )}
      </section>
    </div>
  );

  const renderAutomationSettings = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        {renderWatcherPanel()}
        {renderCurrentTaskPanel()}
      </div>
      {renderRunHistoryPanel()}
    </div>
  );

  const renderAISettings = () => (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        {renderAISettingsPanel()}
        {renderAIWorkspacePanel()}
      </div>
      {renderAIArtifactsPanel()}
    </div>
  );

  const renderMCPSettings = () => (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
      <section className={`${panelClass} p-4`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Plug className="h-4 w-4 text-slate-500" />
              <h2 className="font-semibold text-slate-950">MCP Access</h2>
            </div>
            <div className="mt-1 text-sm text-slate-500">{mcpStatus.server_name}</div>
          </div>
          <button
            onClick={handleToggleMCP}
            disabled={mcpBusy}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ${
              mcpStatus.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {mcpStatus.enabled ? <CheckCircle2 className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
            {mcpStatus.enabled ? 'Enabled' : 'Disabled'}
          </button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          {renderMetricTile('Tools', mcpStatus.tools.length, <SlidersHorizontal className="h-4 w-4" />)}
          {renderMetricTile('Storage', mcpStatus.storage_backend, <Database className="h-4 w-4" />)}
        </div>
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
          <div className="font-medium text-slate-950">{mcpStatus.read_only ? 'Read-only server' : 'Write-capable server'}</div>
          <div className="mt-1 break-all">Config: {mcpStatus.config.exists ? mcpStatus.config.path : 'Missing .mcp.json'}</div>
          <div className="mt-1">Updated: {formatDateTime(mcpStatus.settings?.updated_at)}</div>
        </div>
      </section>

      <section className={`${panelClass} p-4`}>
        <div className="mb-3 flex items-center gap-2">
          <ListPlus className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">Exposed Tools</h2>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {mcpStatus.tools.map(tool => (
            <div key={tool} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
              {tool}
            </div>
          ))}
        </div>
      </section>
    </div>
  );

  const renderDataSettings = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-4">
          {renderStoragePanel()}
          <section className={`${panelClass} p-4`}>
            <div className="mb-3 flex items-center gap-2">
              <FileDown className="h-4 w-4 text-slate-500" />
              <h2 className="font-semibold text-slate-950">Transcript Export</h2>
            </div>
            <div className="grid gap-3">
              <label className="block text-sm font-medium text-slate-700">
                Scope
                <select
                  value={dataExportDraft.scope}
                  onChange={(event) => setDataExportDraft(prev => ({ ...prev, scope: event.target.value as DataExportScope }))}
                  className={`${fieldClass} mt-1`}
                >
                  <option value="all">All transcripts</option>
                  <option value="channel">Channel</option>
                  <option value="search">Current search</option>
                  <option value="collection">Collection transcripts</option>
                  <option value="selected">Selected transcripts</option>
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Format
                <select
                  value={dataExportDraft.format}
                  onChange={(event) => setDataExportDraft(prev => ({ ...prev, format: event.target.value as DataExportFormat }))}
                  className={`${fieldClass} mt-1`}
                >
                  <option value="json">JSON</option>
                  <option value="jsonl">JSONL</option>
                  <option value="csv">CSV</option>
                  <option value="markdown">Markdown</option>
                </select>
              </label>
              {dataExportDraft.scope === 'channel' && (
                <label className="block text-sm font-medium text-slate-700">
                  Channel
                  <select
                    value={dataExportDraft.channel}
                    onChange={(event) => setDataExportDraft(prev => ({ ...prev, channel: event.target.value }))}
                    className={`${fieldClass} mt-1`}
                  >
                    <option value="all">Choose channel</option>
                    {channels.map(channel => <option key={channel} value={channel}>{channel}</option>)}
                  </select>
                </label>
              )}
              {dataExportDraft.scope === 'collection' && (
                <label className="block text-sm font-medium text-slate-700">
                  Collection
                  <select
                    value={dataExportDraft.collectionId || selectedCollectionId}
                    onChange={(event) => setDataExportDraft(prev => ({ ...prev, collectionId: event.target.value }))}
                    className={`${fieldClass} mt-1`}
                  >
                    <option value="">Choose collection</option>
                    {researchOrg.collections.map(collection => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
                  </select>
                </label>
              )}
              {dataExportDraft.scope === 'search' && (
                <label className="block text-sm font-medium text-slate-700">
                  Search query
                  <input
                    value={dataExportDraft.query || searchQuery}
                    onChange={(event) => setDataExportDraft(prev => ({ ...prev, query: event.target.value }))}
                    className={`${fieldClass} mt-1`}
                  />
                </label>
              )}
              <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                <input
                  type="checkbox"
                  checked={dataExportDraft.includeSegments}
                  onChange={(event) => setDataExportDraft(prev => ({ ...prev, includeSegments: event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300 text-blue-600"
                />
                Include timestamp segments
              </label>
              <button onClick={handleDataExport} disabled={dataBusy} className={primaryButtonClass}>
                <Download className="h-4 w-4" />
                Download
              </button>
            </div>
          </section>
        </div>

        <section className={`${panelClass} overflow-hidden`}>
          <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="font-semibold text-slate-950">Read-only Data Browser</h2>
              <div className="text-sm text-slate-500">{dataTable?.total ?? 0} rows in {selectedDataTable}</div>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input value={dataTableQuery} onChange={(event) => setDataTableQuery(event.target.value)} placeholder="Filter rows" className={fieldClass} />
              <button onClick={() => fetchDataTable(selectedDataTable, dataTableQuery)} className={secondaryButtonClass}>
                <RefreshCw className={`h-4 w-4 ${dataBusy ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>
          <div className="grid gap-3 p-3 lg:grid-cols-[220px_minmax(0,1fr)]">
            <div className="space-y-2">
              {dataTables.map(table => (
                <button
                  key={table.name}
                  onClick={() => {
                    setSelectedDataTable(table.name);
                    fetchDataTable(table.name, dataTableQuery);
                  }}
                  className={`flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm ${
                    selectedDataTable === table.name ? 'bg-blue-50 text-blue-700' : 'bg-slate-50 text-slate-700 hover:bg-slate-100'
                  }`}
                >
                  <span className="truncate font-semibold">{table.name}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-500">{table.count}</span>
                </button>
              ))}
            </div>
            <div className="min-w-0 overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                  <tr>
                    {(dataTable?.columns ?? []).map(column => (
                      <th key={column} className="px-3 py-2">{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {(dataTable?.rows ?? []).map((row, rowIndex) => (
                    <tr key={`${dataTable?.name ?? 'row'}-${rowIndex}`}>
                      {(dataTable?.columns ?? []).map(column => (
                        <td key={column} className="max-w-[18rem] truncate px-3 py-2 text-slate-700" title={String(row[column] ?? '')}>
                          {String(row[column] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {(!dataTable || dataTable.rows.length === 0) && (
                <div className="px-4 py-8 text-center text-sm text-slate-500">No rows match this view.</div>
              )}
            </div>
          </div>
        </section>
      </div>
      {renderCollectionsPanel()}
    </div>
  );

  const renderSystemSettings = () => (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <section className={`${panelClass} p-4`}>
        <div className="mb-4 flex items-center gap-2">
          <Cpu className="h-4 w-4 text-slate-500" />
          <h2 className="font-semibold text-slate-950">System Controls</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {renderMetricTile('Backend', apiConnected === false ? 'Offline' : 'Online', <Activity className="h-4 w-4" />, apiConnected === false ? 'text-red-600' : 'text-emerald-600')}
          {renderMetricTile('Watcher', systemStatus.watcher.thread_alive ? 'Running' : 'Stopped', <RefreshCw className="h-4 w-4" />)}
        </div>
        <div className="mt-4 space-y-2">
          <button
            onClick={() => handleUpdateSystemSettings({ ingestion_paused: !systemStatus.settings.ingestion_paused })}
            disabled={systemBusy}
            className={`${secondaryButtonClass} w-full justify-between`}
          >
            <span className="inline-flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Ingestion
            </span>
            <span>{systemStatus.settings.ingestion_paused ? 'Paused' : 'Active'}</span>
          </button>
          <button
            onClick={() => handleUpdateSystemSettings({ maintenance_mode: !systemStatus.settings.maintenance_mode })}
            disabled={systemBusy}
            className={`${secondaryButtonClass} w-full justify-between`}
          >
            <span className="inline-flex items-center gap-2">
              <Settings className="h-4 w-4" />
              Maintenance
            </span>
            <span>{systemStatus.settings.maintenance_mode ? 'On' : 'Off'}</span>
          </button>
        </div>
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
          {systemStatus.backend.message || 'Backend restart and shutdown are managed by the local run script.'}
        </div>
      </section>
      <div className="space-y-4">
        {renderCurrentTaskPanel()}
        {renderActivityPanel()}
      </div>
    </div>
  );

  const renderSettingsContent = () => {
    if (activeSettingsSection === 'ai') return renderAISettings();
    if (activeSettingsSection === 'mcp') return renderMCPSettings();
    if (activeSettingsSection === 'data') return renderDataSettings();
    if (activeSettingsSection === 'system') return renderSystemSettings();
    return renderAutomationSettings();
  };

  const renderSettingsView = () => {
    const settingsSections: { id: SettingsSection; label: string; icon: React.ReactNode }[] = [
      { id: 'automation', label: 'Automation', icon: <RefreshCw className="h-4 w-4" /> },
      { id: 'ai', label: 'AI', icon: <Bot className="h-4 w-4" /> },
      { id: 'mcp', label: 'MCP', icon: <Plug className="h-4 w-4" /> },
      { id: 'data', label: 'Data', icon: <Database className="h-4 w-4" /> },
      { id: 'system', label: 'System', icon: <Cpu className="h-4 w-4" /> },
    ];

    return (
      <div className="space-y-4">
        <section className={`${panelClass} p-4`}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium text-slate-500">
                <Settings className="h-4 w-4" />
                Settings
              </div>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950">Operations Center</h1>
            </div>
            <button
              onClick={() => {
                fetchFetchRuns();
                fetchWatcherSettings();
                fetchAISettings();
                fetchAIModels();
                fetchAIArtifacts();
                fetchEmbeddingStatus();
                fetchMcpStatus();
                fetchSystemStatus();
                fetchDataTables();
                if (activeSettingsSection === 'data') {
                  fetchDataTable(selectedDataTable, dataTableQuery);
                }
              }}
              className={secondaryButtonClass}
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
          <nav className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {settingsSections.map(section => (
              <button
                key={section.id}
                onClick={() => setActiveSettingsSection(section.id)}
                className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${
                  activeSettingsSection === section.id ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
                }`}
              >
                {section.icon}
                {section.label}
              </button>
            ))}
          </nav>
        </section>
        {renderSettingsContent()}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-600">
                <Youtube className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-lg font-semibold text-slate-950">YouTube Transcript Pro</h1>
                <p className="truncate text-sm text-slate-500">
                  {libraryStats ? `${libraryStats.transcript_count} transcripts, ${formatCompactNumber(libraryStats.total_words)} words` : 'Local transcript archive'}
                </p>
              </div>
            </div>
            <button onClick={fetchTranscripts} className={`${iconButtonClass} lg:hidden`} title="Refresh">
              <RefreshCw className={`h-4 w-4 ${transcriptsLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div
              className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${
                apiConnected === false
                  ? 'bg-red-50 text-red-700'
                  : apiConnected === null
                    ? 'bg-slate-100 text-slate-600'
                    : 'bg-emerald-50 text-emerald-700'
              }`}
              title={apiConnected === false ? 'Backend API is not reachable' : 'Backend API status'}
            >
              {apiConnected === false ? (
                <AlertTriangle className="h-4 w-4" />
              ) : apiConnected === null ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              {apiConnected === false ? 'Backend offline' : apiConnected === null ? 'Checking API' : 'Backend connected'}
            </div>

            <nav className="grid grid-cols-2 gap-2 sm:flex">
              <button
                onClick={() => setActiveView('library')}
                className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${
                  activeView === 'library' ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
                }`}
              >
                <Search className="h-4 w-4" />
                Library
              </button>
              <button
                onClick={() => {
                  setActiveView('settings');
                fetchWatcherSettings();
                fetchFetchRuns();
                fetchAISettings();
                fetchAIModels();
                fetchAIArtifacts();
                fetchEmbeddingStatus();
              }}
                className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${
                  activeView === 'settings' ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
                }`}
              >
                <Settings className="h-4 w-4" />
                Settings
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-4 sm:px-6">
        {activeView === 'settings' ? renderSettingsView() : renderLibraryView()}
      </main>
    </div>
  );
}

export default App;
