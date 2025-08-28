"use client";

import { useState, useEffect, useRef, useCallback } from 'react';
import { OpenStackEvent, WebSocketFilter, ConnectionStatus } from '../types';

interface UseWebSocketOptions {
  autoConnect?: boolean;
  reconnectAttempts?: number;
  reconnectInterval?: number;
  onEvent?: (event: OpenStackEvent) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

interface UseWebSocketReturn {
  events: OpenStackEvent[];
  connectionStatus: ConnectionStatus;
  connect: () => void;
  disconnect: () => void;
  clearEvents: () => void;
  setFilters: (filters: WebSocketFilter) => void;
  sendMessage: (message: Record<string, unknown>) => void;
}

export const useWebSocket = (
  url: string,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn => {
  const {
    autoConnect = true,
    reconnectAttempts = 5,
    reconnectInterval = 5000,
    onEvent,
    onConnect,
    onDisconnect,
    onError
  } = options;

  const [events, setEvents] = useState<OpenStackEvent[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    connected: false
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const reconnectAttemptsRef = useRef(0);
  const isConnectingRef = useRef(false);

  const addEvent = useCallback((event: OpenStackEvent) => {
    setEvents(prev => [event, ...prev].slice(0, 1000)); // Keep last 1000 events
    onEvent?.(event);
  }, [onEvent]);

  const connect = useCallback(() => {
    if (!url || isConnectingRef.current || (wsRef.current?.readyState === WebSocket.OPEN)) {
      return;
    }

    isConnectingRef.current = true;

    try {
      // Convert http/https URL to ws/wss for WebSocket
      const wsUrl = url.replace(/^http/, 'ws');
      console.log('Attempting WebSocket connection to:', wsUrl);
      const websocket = new WebSocket(wsUrl);

      websocket.onopen = () => {
        console.log('WebSocket connected:', wsUrl);
        isConnectingRef.current = false;
        reconnectAttemptsRef.current = 0;

        setConnectionStatus({
          connected: true,
          lastConnected: new Date()
        });

        onConnect?.();
      };

      websocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // Handle filter acknowledgment messages
          if (data.type === 'filter_update') {
            console.log('Filters updated:', data);
            return;
          }

          // Handle OpenStack events
          if (data.event_type) {
            addEvent(data as OpenStackEvent);
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      websocket.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        isConnectingRef.current = false;
        wsRef.current = null;

        setConnectionStatus({
          connected: false,
          error: event.reason || 'Connection closed'
        });

        onDisconnect?.();

        // Attempt reconnection if not manually closed
        if (event.code !== 1000 && reconnectAttemptsRef.current < reconnectAttempts) {
          reconnectAttemptsRef.current++;
          console.log(`Attempting reconnect ${reconnectAttemptsRef.current}/${reconnectAttempts}`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };

      websocket.onerror = (error) => {
        console.error('WebSocket error:', error);
        console.error('WebSocket URL was:', wsUrl);
        isConnectingRef.current = false;

        setConnectionStatus({
          connected: false,
          error: 'Connection error - check console for details'
        });

        onError?.(error);
      };

      wsRef.current = websocket;

    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      isConnectingRef.current = false;

      setConnectionStatus({
        connected: false,
        error: 'Failed to connect'
      });
    }
  }, [url, reconnectAttempts, reconnectInterval, onConnect, onDisconnect, onError, addEvent]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Manual disconnect');
      wsRef.current = null;
    }

    reconnectAttemptsRef.current = reconnectAttempts; // Prevent reconnection
    isConnectingRef.current = false;

    setConnectionStatus({
      connected: false
    });
  }, [reconnectAttempts]);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const setFilters = useCallback((filters: WebSocketFilter) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = {
        action: 'set_filters',
        ...filters
      };
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  const sendMessage = useCallback((message: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    events,
    connectionStatus,
    connect,
    disconnect,
    clearEvents,
    setFilters,
    sendMessage
  };
};

export default useWebSocket;