export interface BaremetalNode {
  uuid: string;
  name: string | null;
  power_state: string | null;
  provision_state: string | null;
  maintenance: boolean | null;
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

// Event-related types for WebSocket streaming
export interface OpenStackEvent {
  id: string;
  timestamp: string;
  event_type: string;
  source: "openstack";
  node_name: string | null;
  data: {
    service_type: string;
    resource_id?: string;
    [key: string]: unknown;
  };
}

export interface BaremetalEvent extends OpenStackEvent {
  data: {
    service_type: "baremetal";
    resource_id: string;
    ironic_object: {
      data: {
        name: string;
        uuid: string;
        power_state?: string;
        provision_state?: string;
        maintenance?: boolean;
        [key: string]: unknown;
      };
    };
  };
}

export interface WebSocketFilter {
  event_filters?: string[];
  node_filters?: string[];
  service_filters?: string[];
}

export interface ConnectionStatus {
  connected: boolean;
  lastConnected?: Date;
  error?: string;
}