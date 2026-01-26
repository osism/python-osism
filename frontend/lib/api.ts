import axios, { AxiosInstance } from 'axios';
import {
  BaremetalNodesResponse,
  HealthCheckResponse,
  HostsResponse,
  HostvarsResponse,
  HostvarSingleResponse,
  FactsResponse,
  FactSingleResponse,
  SearchResponse,
} from './types';

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

  inventory: {
    getHosts: async (limit?: string): Promise<HostsResponse> => {
      const client = await getApiClient();
      const params = limit ? { limit } : undefined;
      const response = await client.get<HostsResponse>('/v1/inventory/hosts', { params });
      return response.data;
    },

    getHostvars: async (host: string): Promise<HostvarsResponse> => {
      const client = await getApiClient();
      const response = await client.get<HostvarsResponse>(`/v1/inventory/hosts/${encodeURIComponent(host)}/hostvars`);
      return response.data;
    },

    getHostvar: async (host: string, variable: string): Promise<HostvarSingleResponse> => {
      const client = await getApiClient();
      const response = await client.get<HostvarSingleResponse>(
        `/v1/inventory/hosts/${encodeURIComponent(host)}/hostvars/${encodeURIComponent(variable)}`
      );
      return response.data;
    },

    getFacts: async (host: string): Promise<FactsResponse> => {
      const client = await getApiClient();
      const response = await client.get<FactsResponse>(`/v1/inventory/hosts/${encodeURIComponent(host)}/facts`);
      return response.data;
    },

    getFact: async (host: string, fact: string): Promise<FactSingleResponse> => {
      const client = await getApiClient();
      const response = await client.get<FactSingleResponse>(
        `/v1/inventory/hosts/${encodeURIComponent(host)}/facts/${encodeURIComponent(fact)}`
      );
      return response.data;
    },

    search: async (params: {
      name_pattern: string;
      host_pattern?: string;
      source?: 'hostvars' | 'facts';
      limit?: number;
    }): Promise<SearchResponse> => {
      const client = await getApiClient();
      const response = await client.get<SearchResponse>('/v1/inventory/search', { params });
      return response.data;
    },
  },
};

export default api;
