/** Display helpers: dates, counts, runtimes, and query matching. */

import { SAVED_SEARCHES_KEY } from './constants';
import type { Transcript } from '../types';

export const getDisplayDateValue = (item: { uploaded_at?: string; saved_at?: string }) => (
  item.uploaded_at || item.saved_at || ''
);

export const parseDisplayDateMillis = (value?: string | null) => {
  if (!value) return 0;
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    return new Date(
      Number(dateOnly[1]),
      Number(dateOnly[2]) - 1,
      Number(dateOnly[3]),
    ).getTime();
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
};

export const formatDisplayDateTime = (value?: string | null) => {
  if (!value) return 'Pending';
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    return new Date(
      Number(dateOnly[1]),
      Number(dateOnly[2]) - 1,
      Number(dateOnly[3]),
    ).toLocaleDateString();
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

export const countWords = (text: string) => (
  text.trim().split(/\s+/).filter(Boolean).length
);

export const getTranscriptRuntime = (transcript: Transcript | null | undefined) => {
  // List rows carry a precomputed duration; only a fetched detail has segments.
  if (transcript?.duration_seconds != null) return transcript.duration_seconds;
  if (!transcript?.segments?.length) return 0;

  return Math.max(...transcript.segments.map(segment => segment.start + segment.duration));
};

export const getQueryTerms = (query: string) => (
  Array.from(new Set(query.trim().toLowerCase().split(/\s+/).filter(term => term.length > 1)))
);

export const countQueryMatches = (text: string, query: string) => {
  const lowerText = text.toLowerCase();

  return getQueryTerms(query).reduce((total, term) => {
    let count = 0;
    let index = lowerText.indexOf(term);

    while (index !== -1) {
      count += 1;
      index = lowerText.indexOf(term, index + term.length);
    }

    return total + count;
  }, 0);
};

export const parseSavedSearches = () => {
  try {
    const raw = window.localStorage.getItem(SAVED_SEARCHES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    return parsed.filter((item): item is string => typeof item === 'string');
  } catch {
    return [];
  }
};
