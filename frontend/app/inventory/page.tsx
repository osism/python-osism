"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  Search,
  AlertCircle,
  ChevronRight,
  Server,
  Database,
  FileJson,
  Copy,
  Check,
} from "lucide-react";
import api from "@/lib/api";
import { HostvarEntry, FactEntry } from "@/lib/types";

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1 text-gray-400 hover:text-gray-600 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-4 w-4 text-green-500" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </button>
  );
}

function DataTable({
  entries,
  searchTerm,
  emptyMessage,
}: {
  entries: (HostvarEntry | FactEntry)[];
  searchTerm: string;
  emptyMessage: string;
}) {
  const filteredEntries = entries.filter((entry) =>
    entry.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (filteredEntries.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        {searchTerm ? "No matching entries found" : emptyMessage}
      </div>
    );
  }

  return (
    <div className="divide-y divide-gray-200">
      {filteredEntries.map((entry, index) => (
        <div key={`${entry.name}-${index}`} className="py-3">
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">
                  {entry.name}
                </span>
                <CopyButton text={entry.name} />
              </div>
              <pre className="mt-1 text-sm text-gray-600 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded max-h-48 overflow-auto">
                {formatValue(entry.value)}
              </pre>
            </div>
            <CopyButton text={formatValue(entry.value)} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function InventoryPage() {
  const [selectedHost, setSelectedHost] = useState<string | null>(null);
  const [hostSearchTerm, setHostSearchTerm] = useState("");
  const [varSearchTerm, setVarSearchTerm] = useState("");
  const [factSearchTerm, setFactSearchTerm] = useState("");
  const [activeTab, setActiveTab] = useState<"hostvars" | "facts">("hostvars");

  // Fetch hosts
  const {
    data: hostsData,
    isLoading: hostsLoading,
    error: hostsError,
    refetch: refetchHosts,
    isRefetching: hostsRefetching,
  } = useQuery({
    queryKey: ["inventory-hosts"],
    queryFn: () => api.inventory.getHosts(),
    refetchInterval: 60000,
  });

  // Fetch hostvars for selected host
  const {
    data: hostvarsData,
    isLoading: hostvarsLoading,
    error: hostvarsError,
    refetch: refetchHostvars,
  } = useQuery({
    queryKey: ["inventory-hostvars", selectedHost],
    queryFn: () => api.inventory.getHostvars(selectedHost!),
    enabled: !!selectedHost,
  });

  // Fetch facts for selected host
  const {
    data: factsData,
    isLoading: factsLoading,
    error: factsError,
    refetch: refetchFacts,
  } = useQuery({
    queryKey: ["inventory-facts", selectedHost],
    queryFn: () => api.inventory.getFacts(selectedHost!),
    enabled: !!selectedHost,
    retry: false,
  });

  const filteredHosts =
    hostsData?.hosts.filter((host) =>
      host.toLowerCase().includes(hostSearchTerm.toLowerCase())
    ) || [];

  return (
    <div className="px-4 sm:px-0">
      <div className="sm:flex sm:items-center sm:justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Inventory</h2>
          <p className="mt-1 text-sm text-gray-600">
            View host variables and cached Ansible facts
          </p>
        </div>
        <button
          onClick={() => {
            refetchHosts();
            if (selectedHost) {
              refetchHostvars();
              refetchFacts();
            }
          }}
          disabled={hostsRefetching}
          className="mt-4 sm:mt-0 inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          <RefreshCw
            className={`h-4 w-4 mr-2 ${hostsRefetching ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Hosts Panel */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 border-b border-gray-200">
            <div className="flex items-center gap-2">
              <Server className="h-5 w-5 text-gray-500" />
              <h3 className="text-lg font-medium text-gray-900">Hosts</h3>
              {hostsData && (
                <span className="text-sm text-gray-500">
                  ({hostsData.count})
                </span>
              )}
            </div>
            <div className="mt-3 relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Search className="h-4 w-4 text-gray-400" />
              </div>
              <input
                type="text"
                className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                placeholder="Search hosts..."
                value={hostSearchTerm}
                onChange={(e) => setHostSearchTerm(e.target.value)}
              />
            </div>
          </div>

          <div className="max-h-[500px] overflow-y-auto">
            {hostsError && (
              <div className="p-4">
                <div className="flex items-center text-red-600">
                  <AlertCircle className="h-5 w-5 mr-2" />
                  <span className="text-sm">Failed to load hosts</span>
                </div>
              </div>
            )}

            {hostsLoading ? (
              <div className="p-4">
                <div className="animate-pulse space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="h-8 bg-gray-200 rounded"></div>
                  ))}
                </div>
              </div>
            ) : filteredHosts.length > 0 ? (
              <ul className="divide-y divide-gray-200">
                {filteredHosts.map((host) => (
                  <li key={host}>
                    <button
                      onClick={() => setSelectedHost(host)}
                      className={`w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors ${
                        selectedHost === host ? "bg-blue-50" : ""
                      }`}
                    >
                      <span
                        className={`text-sm ${
                          selectedHost === host
                            ? "font-medium text-blue-700"
                            : "text-gray-700"
                        }`}
                      >
                        {host}
                      </span>
                      <ChevronRight
                        className={`h-4 w-4 ${
                          selectedHost === host
                            ? "text-blue-500"
                            : "text-gray-400"
                        }`}
                      />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="p-4 text-center text-gray-500 text-sm">
                {hostSearchTerm ? "No matching hosts" : "No hosts found"}
              </div>
            )}
          </div>
        </div>

        {/* Details Panel */}
        <div className="lg:col-span-2 bg-white shadow rounded-lg">
          {!selectedHost ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-gray-500">
              <Server className="h-12 w-12 mb-4" />
              <p>Select a host to view details</p>
            </div>
          ) : (
            <>
              <div className="px-4 py-5 border-b border-gray-200">
                <h3 className="text-lg font-medium text-gray-900">
                  {selectedHost}
                </h3>

                {/* Tabs */}
                <div className="mt-4 flex space-x-4">
                  <button
                    onClick={() => setActiveTab("hostvars")}
                    className={`flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                      activeTab === "hostvars"
                        ? "bg-blue-100 text-blue-700"
                        : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                    }`}
                  >
                    <Database className="h-4 w-4" />
                    Host Variables
                    {hostvarsData && (
                      <span className="text-xs">({hostvarsData.count})</span>
                    )}
                  </button>
                  <button
                    onClick={() => setActiveTab("facts")}
                    className={`flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                      activeTab === "facts"
                        ? "bg-blue-100 text-blue-700"
                        : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                    }`}
                  >
                    <FileJson className="h-4 w-4" />
                    Facts (Cache)
                    {factsData && (
                      <span className="text-xs">({factsData.count})</span>
                    )}
                  </button>
                </div>
              </div>

              <div className="p-4">
                {/* Search bar for current tab */}
                <div className="mb-4 relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Search className="h-4 w-4 text-gray-400" />
                  </div>
                  <input
                    type="text"
                    className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                    placeholder={`Search ${activeTab === "hostvars" ? "variables" : "facts"}...`}
                    value={activeTab === "hostvars" ? varSearchTerm : factSearchTerm}
                    onChange={(e) =>
                      activeTab === "hostvars"
                        ? setVarSearchTerm(e.target.value)
                        : setFactSearchTerm(e.target.value)
                    }
                  />
                </div>

                {/* Content based on active tab */}
                <div className="max-h-[400px] overflow-y-auto">
                  {activeTab === "hostvars" ? (
                    <>
                      {hostvarsError && (
                        <div className="flex items-center text-red-600 mb-4">
                          <AlertCircle className="h-5 w-5 mr-2" />
                          <span className="text-sm">
                            Failed to load host variables
                          </span>
                        </div>
                      )}

                      {hostvarsLoading ? (
                        <div className="animate-pulse space-y-3">
                          {[1, 2, 3].map((i) => (
                            <div key={i}>
                              <div className="h-4 bg-gray-200 rounded w-1/4 mb-2"></div>
                              <div className="h-16 bg-gray-200 rounded"></div>
                            </div>
                          ))}
                        </div>
                      ) : hostvarsData ? (
                        <DataTable
                          entries={hostvarsData.variables}
                          searchTerm={varSearchTerm}
                          emptyMessage="No host variables found"
                        />
                      ) : null}
                    </>
                  ) : (
                    <>
                      {factsError && (
                        <div className="flex items-center text-yellow-600 mb-4">
                          <AlertCircle className="h-5 w-5 mr-2" />
                          <span className="text-sm">
                            No facts in cache for this host. Run `osism apply
                            facts` to populate the cache.
                          </span>
                        </div>
                      )}

                      {factsLoading ? (
                        <div className="animate-pulse space-y-3">
                          {[1, 2, 3].map((i) => (
                            <div key={i}>
                              <div className="h-4 bg-gray-200 rounded w-1/4 mb-2"></div>
                              <div className="h-16 bg-gray-200 rounded"></div>
                            </div>
                          ))}
                        </div>
                      ) : factsData ? (
                        <DataTable
                          entries={factsData.facts}
                          searchTerm={factSearchTerm}
                          emptyMessage="No facts found"
                        />
                      ) : null}
                    </>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
