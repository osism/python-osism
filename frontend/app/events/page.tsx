"use client";

import { useState, useEffect, useCallback } from "react";
import { Activity, RefreshCw, Trash2 } from "lucide-react";
import useWebSocket from "@/lib/hooks/useWebSocket";
import EventsList from "../components/EventsList";
import EventsFilters from "../components/EventsFilters";
import ConnectionStatus from "../components/ConnectionStatus";
import { WebSocketFilter } from "@/lib/types";

async function getWebSocketUrl(): Promise<string> {
  if (typeof window !== 'undefined') {
    try {
      const response = await fetch('/api/config');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const config = await response.json();
      // Convert HTTP URL to WebSocket URL
      const apiUrl = config.apiUrl.replace(/^http/, 'ws');
      const wsUrl = `${apiUrl}/v1/events/openstack`;
      console.log('Using WebSocket URL from config:', wsUrl);
      return wsUrl;
    } catch (error) {
      console.warn('Failed to fetch API config for WebSocket:', error);
      const fallbackUrl = 'ws://localhost:8000/v1/events/openstack';
      console.log('Using fallback WebSocket URL:', fallbackUrl);
      return fallbackUrl;
    }
  }
  // Server-side fallback
  const apiUrl = (process.env.NEXT_PUBLIC_OSISM_API_URL || 'http://api:8000').replace(/^http/, 'ws');
  const wsUrl = `${apiUrl}/v1/events/openstack`;
  console.log('Using server-side WebSocket URL:', wsUrl);
  return wsUrl;
}

export default function EventsPage() {
  const [wsUrl, setWsUrl] = useState<string>('');
  const [eventCount, setEventCount] = useState(0);

  // Initialize WebSocket URL
  useEffect(() => {
    getWebSocketUrl().then((url) => {
      console.log('WebSocket URL resolved:', url);
      setWsUrl(url);
    });
  }, []);

  const {
    events,
    connectionStatus,
    connect,
    disconnect,
    clearEvents,
    setFilters
  } = useWebSocket(wsUrl, {
    autoConnect: false, // Don't auto-connect until URL is ready
    onEvent: useCallback(() => {
      setEventCount(prev => prev + 1);
    }, [])
  });

  // Connect only after wsUrl is available
  useEffect(() => {
    if (wsUrl) {
      connect();
    }
  }, [wsUrl, connect]);

  const handleFiltersChange = useCallback((filters: WebSocketFilter) => {
    setFilters(filters);
  }, [setFilters]);

  const handleReconnect = () => {
    disconnect();
    setTimeout(() => {
      connect();
    }, 100);
  };

  const handleClearEvents = () => {
    clearEvents();
    setEventCount(0);
  };

  if (!wsUrl) {
    return (
      <div className="px-4 sm:px-0">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="h-4 bg-gray-200 rounded w-1/2"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-0">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900 flex items-center">
              <Activity className="h-7 w-7 mr-3" />
              Events
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              Real-time Baremetal events from OpenStack Ironic
            </p>
          </div>

          {/* Connection Status */}
          <ConnectionStatus status={connectionStatus} />
        </div>
      </div>

      {/* Stats & Controls */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-4 sm:space-y-0">
        <div className="flex items-center space-x-4">
          <div className="bg-white px-4 py-2 rounded-lg border border-gray-200">
            <div className="flex items-center">
              <Activity className="h-4 w-4 text-gray-400 mr-2" />
              <span className="text-sm font-medium text-gray-700">
                {events.length} events
              </span>
              {eventCount > 0 && (
                <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                  +{eventCount} new
                </span>
              )}
            </div>
          </div>

          <EventsFilters onFiltersChange={handleFiltersChange} />
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={handleReconnect}
            className="inline-flex items-center px-3 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
            disabled={connectionStatus.connected}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Reconnect
          </button>

          <button
            onClick={handleClearEvents}
            className="inline-flex items-center px-3 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
            disabled={events.length === 0}
          >
            <Trash2 className="h-4 w-4 mr-2" />
            Clear Events
          </button>
        </div>
      </div>

      {/* Connection Warning */}
      {!connectionStatus.connected && (
        <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <Activity className="h-5 w-5 text-yellow-400" />
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-yellow-800">
                Connection Issue
              </h3>
              <div className="mt-2 text-sm text-yellow-700">
                <p>
                  Unable to connect to the events stream. Events may not appear in real-time.
                  {connectionStatus.error && ` Error: ${connectionStatus.error}`}
                </p>
              </div>
              <div className="mt-4">
                <div className="-mx-2 -my-1.5 flex">
                  <button
                    onClick={handleReconnect}
                    className="bg-yellow-50 px-2 py-1.5 rounded-md text-sm font-medium text-yellow-800 hover:bg-yellow-100"
                  >
                    Try Reconnecting
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Events List */}
      <div className="bg-gray-50 rounded-lg p-6">
        <EventsList events={events} />
      </div>
    </div>
  );
}