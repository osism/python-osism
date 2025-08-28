"use client";

import { useMemo, useState } from "react";
import { format } from "date-fns";
import {
  Server,
  Power,
  Settings,
  Trash2,
  Plus,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Pause,
  Play
} from "lucide-react";
import { OpenStackEvent, BaremetalEvent } from "@/lib/types";

interface EventsListProps {
  events: OpenStackEvent[];
  className?: string;
}

const getEventIcon = (eventType: string) => {
  if (eventType.includes("power")) return Power;
  if (eventType.includes("provision")) return Settings;
  if (eventType.includes("maintenance")) return AlertTriangle;
  if (eventType.includes("create")) return Plus;
  if (eventType.includes("delete")) return Trash2;
  return Server;
};

const getEventColor = (eventType: string) => {
  if (eventType.includes("power_set.end")) return "text-blue-600 bg-blue-50";
  if (eventType.includes("provision_set.success")) return "text-green-600 bg-green-50";
  if (eventType.includes("provision_set.start")) return "text-yellow-600 bg-yellow-50";
  if (eventType.includes("maintenance")) return "text-orange-600 bg-orange-50";
  if (eventType.includes("create")) return "text-green-600 bg-green-50";
  if (eventType.includes("delete")) return "text-red-600 bg-red-50";
  return "text-gray-600 bg-gray-50";
};

const getStatusIcon = (eventType: string) => {
  if (eventType.includes("success")) return CheckCircle;
  if (eventType.includes("error") || eventType.includes("fail")) return XCircle;
  if (eventType.includes("start")) return Clock;
  return null;
};

const formatEventData = (event: OpenStackEvent) => {
  if (event.data.service_type === "baremetal" && "ironic_object" in event.data) {
    const baremetalEvent = event as BaremetalEvent;
    const ironicData = baremetalEvent.data.ironic_object?.data;

    if (!ironicData) return null;

    const details = [];
    if (ironicData.power_state) details.push(`Power: ${ironicData.power_state}`);
    if (ironicData.provision_state) details.push(`Provision: ${ironicData.provision_state}`);
    if (ironicData.maintenance !== undefined) details.push(`Maintenance: ${ironicData.maintenance ? "Yes" : "No"}`);

    return details.join(" | ");
  }

  return null;
};

export default function EventsList({ events, className = "" }: EventsListProps) {
  const [isPaused, setIsPaused] = useState(false);
  const [maxEvents, setMaxEvents] = useState(50);

  const displayEvents = useMemo(() => {
    return isPaused ? events : events.slice(0, maxEvents);
  }, [events, isPaused, maxEvents]);

  const togglePause = () => {
    setIsPaused(!isPaused);
  };

  const loadMore = () => {
    setMaxEvents(prev => prev + 50);
  };

  if (events.length === 0) {
    return (
      <div className={`text-center py-12 ${className}`}>
        <Server className="mx-auto h-12 w-12 text-gray-400" />
        <h3 className="mt-2 text-sm font-medium text-gray-900">No events yet</h3>
        <p className="mt-1 text-sm text-gray-500">
          Baremetal events will appear here in real-time.
        </p>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* Controls */}
      <div className="flex items-center justify-between mb-4 text-sm text-gray-600">
        <span>{events.length} events total</span>
        <div className="flex items-center space-x-2">
          <button
            onClick={togglePause}
            className="inline-flex items-center px-3 py-1 border border-gray-300 rounded-md hover:bg-gray-50"
          >
            {isPaused ? (
              <>
                <Play className="h-4 w-4 mr-1" />
                Resume
              </>
            ) : (
              <>
                <Pause className="h-4 w-4 mr-1" />
                Pause
              </>
            )}
          </button>
        </div>
      </div>

      {/* Events List */}
      <div className="space-y-1">
        {displayEvents.map((event) => {
          const Icon = getEventIcon(event.event_type);
          const StatusIcon = getStatusIcon(event.event_type);
          const colorClass = getEventColor(event.event_type);
          const eventDetails = formatEventData(event);

          return (
            <div
              key={event.id}
              className="flex items-start space-x-3 p-3 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors"
            >
              {/* Icon */}
              <div className={`flex-shrink-0 p-2 rounded-lg ${colorClass}`}>
                <Icon className="h-4 w-4" />
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="text-sm font-medium text-gray-900 font-mono">
                      {event.event_type}
                    </span>
                    {StatusIcon && (
                      <StatusIcon className="h-4 w-4 text-gray-400" />
                    )}
                  </div>
                  <time className="text-xs text-gray-500 flex-shrink-0">
                    {format(new Date(event.timestamp), "HH:mm:ss")}
                  </time>
                </div>

                {event.node_name && (
                  <div className="flex items-center mt-1">
                    <Server className="h-3 w-3 text-gray-400 mr-1" />
                    <span className="text-sm font-medium text-gray-700">
                      {event.node_name}
                    </span>
                  </div>
                )}

                {eventDetails && (
                  <p className="text-sm text-gray-600 mt-1">
                    {eventDetails}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Load More */}
      {!isPaused && events.length > maxEvents && (
        <div className="mt-4 text-center">
          <button
            onClick={loadMore}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Load More Events ({events.length - maxEvents} remaining)
          </button>
        </div>
      )}
    </div>
  );
}