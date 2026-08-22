/** Turning an axios failure into something worth showing a person. */

import axios from 'axios';

export const getApiErrorDetails = (error: unknown): Record<string, unknown> => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    const detail = data && typeof data === 'object' && 'detail' in data
      ? (data as { detail?: unknown }).detail
      : data;

    return {
      message: error.message,
      status: error.response?.status ?? 'network',
      method: error.config?.method?.toUpperCase(),
      url: error.config?.url,
      detail,
    };
  }

  if (error instanceof Error) {
    return { message: error.message };
  }

  return { message: String(error) };
};

export const getApiErrorSummary = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    const detail = data && typeof data === 'object' && 'detail' in data
      ? (data as { detail?: unknown }).detail
      : data;

    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (error.response?.status) {
      return `HTTP ${error.response.status}`;
    }
    return error.message || 'Network error';
  }

  return error instanceof Error ? error.message : String(error);
};

export const isConnectivityError = (error: unknown) => axios.isAxiosError(error) && !error.response;
