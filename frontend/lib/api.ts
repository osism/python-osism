import axios from 'axios';
import { BaremetalNodesResponse, HealthCheckResponse } from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const api = {
  health: {
    check: async (): Promise<HealthCheckResponse> => {
      const response = await apiClient.get<HealthCheckResponse>('/v1');
      return response.data;
    },
  },

  baremetal: {
    getNodes: async (): Promise<BaremetalNodesResponse> => {
      const response = await apiClient.get<BaremetalNodesResponse>('/v1/baremetal/nodes');
      return response.data;
    },
  },
};

export default api;