export interface BaremetalNode {
  uuid: string;
  name: string | null;
  power_state: string | null;
  provision_state: string | null;
  maintenance: boolean;
  instance_uuid: string | null;
  driver: string | null;
  resource_class: string | null;
  properties: Record<string, unknown>;
  extra: Record<string, unknown>;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BaremetalNodesResponse {
  nodes: BaremetalNode[];
  count: number;
}

export interface HealthCheckResponse {
  result: string;
}

export interface DeviceSearchResult {
  result: string;
  device: string | null;
}