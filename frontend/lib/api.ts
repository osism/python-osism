import axios, { AxiosInstance } from 'axios';
import { BaremetalNodesResponse, HealthCheckResponse } from './types';

const API_URL = 'http://api:8000'; // Default fallback
let apiClient: AxiosInstance | null = null;

async function getApiUrl(): Promise<string> {
  if (typeof window !== 'undefined') {
    try {
      const response = await fetch('/api/config');
      const config = await response.json();
      return config.apiUrl;
    } catch {
      console.warn('Failed to fetch API config, using fallback');
      return API_URL;
    }
  }
  return process.env.NEXT_PUBLIC_OSISM_API_URL || API_URL;
}

async function getApiClient() {
  if (!apiClient) {
    const baseURL = await getApiUrl();
    apiClient = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }
  return apiClient;
}

export const api = {
  health: {
    check: async (): Promise<HealthCheckResponse> => {
      const client = await getApiClient();
      const response = await client.get<HealthCheckResponse>('/v1');
      return response.data;
    },
  },

  baremetal: {
    getNodes: async (): Promise<BaremetalNodesResponse> => {
      const client = await getApiClient();
      const response = await client.get<BaremetalNodesResponse>('/v1/baremetal/nodes');
      return response.data;
    },
  },
};

export default api;
