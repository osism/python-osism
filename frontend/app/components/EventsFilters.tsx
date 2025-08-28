"use client";

import { useState, useCallback } from "react";
import { Filter, X } from "lucide-react";
import { WebSocketFilter } from "@/lib/types";

interface EventsFiltersProps {
  onFiltersChange: (filters: WebSocketFilter) => void;
  className?: string;
}

const BAREMETAL_EVENT_TYPES = [
  "baremetal.node.power_set.end",
  "baremetal.node.provision_set.start",
  "baremetal.node.provision_set.end",
  "baremetal.node.provision_set.success",
  "baremetal.node.power_state_corrected.success",
  "baremetal.node.maintenance_set.end",
  "baremetal.node.create.end",
  "baremetal.node.delete.end",
];

export default function EventsFilters({ onFiltersChange, className = "" }: EventsFiltersProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [nodeFilter, setNodeFilter] = useState("");

  const applyFilters = useCallback(() => {
    const filters: WebSocketFilter = {
      service_filters: ["baremetal"], // Always filter for baremetal events
    };

    if (selectedEventTypes.length > 0) {
      filters.event_filters = selectedEventTypes;
    }

    if (nodeFilter.trim()) {
      filters.node_filters = nodeFilter.split(",").map(n => n.trim()).filter(n => n);
    }

    onFiltersChange(filters);
    setIsOpen(false);
  }, [selectedEventTypes, nodeFilter, onFiltersChange]);

  const clearFilters = useCallback(() => {
    setSelectedEventTypes([]);
    setNodeFilter("");
    onFiltersChange({ service_filters: ["baremetal"] });
  }, [onFiltersChange]);

  const toggleEventType = useCallback((eventType: string) => {
    setSelectedEventTypes(prev =>
      prev.includes(eventType)
        ? prev.filter(t => t !== eventType)
        : [...prev, eventType]
    );
  }, []);

  const hasActiveFilters = selectedEventTypes.length > 0 || nodeFilter.trim().length > 0;

  return (
    <div className={`relative ${className}`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`inline-flex items-center px-4 py-2 border rounded-md text-sm font-medium transition-colors ${
          hasActiveFilters
            ? "border-blue-500 bg-blue-50 text-blue-700"
            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
        }`}
      >
        <Filter className="h-4 w-4 mr-2" />
        Filters
        {hasActiveFilters && (
          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
            {(selectedEventTypes.length > 0 ? 1 : 0) + (nodeFilter ? 1 : 0)}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-96 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
          <div className="p-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-900">Event Filters</h3>
              <button
                onClick={() => setIsOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* Node Filter */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Node Names (comma-separated)
              </label>
              <input
                type="text"
                value={nodeFilter}
                onChange={(e) => setNodeFilter(e.target.value)}
                placeholder="e.g., server-01, server-02"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Event Type Filter */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Event Types
              </label>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {BAREMETAL_EVENT_TYPES.map((eventType) => (
                  <label key={eventType} className="flex items-center">
                    <input
                      type="checkbox"
                      checked={selectedEventTypes.includes(eventType)}
                      onChange={() => toggleEventType(eventType)}
                      className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                    />
                    <span className="ml-2 text-sm text-gray-700 font-mono">
                      {eventType}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="p-4 border-t border-gray-200 flex justify-between">
            <button
              onClick={clearFilters}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Clear All
            </button>
            <button
              onClick={applyFilters}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700"
            >
              Apply Filters
            </button>
          </div>
        </div>
      )}
    </div>
  );
}