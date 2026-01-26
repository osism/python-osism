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
  Filter,
  X,
} from "lucide-react";
import api from "@/lib/api";
import { HostvarEntry, FactEntry, SearchResultEntry } from "@/lib/types";

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function getValueType(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function getTypeColor(value: unknown): string {
  const type = getValueType(value);
  switch (type) {
    case "string":
      return "bg-green-100 text-green-800 border-green-200";
    case "number":
      return "bg-blue-100 text-blue-800 border-blue-200";
    case "boolean":
      return "bg-purple-100 text-purple-800 border-purple-200";
    case "array":
      return "bg-orange-100 text-orange-800 border-orange-200";
    case "object":
      return "bg-yellow-100 text-yellow-800 border-yellow-200";
    case "null":
      return "bg-gray-100 text-gray-600 border-gray-200";
    default:
      return "bg-gray-100 text-gray-800 border-gray-200";
  }
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
    <div className="space-y-2">
      {filteredEntries.map((entry, index) => (
        <div
          key={`${entry.name}-${index}`}
          className={`p-3 rounded-lg border ${
            index % 2 === 0
              ? "bg-white border-gray-200"
              : "bg-gray-50 border-gray-100"
          } hover:border-blue-300 hover:shadow-sm transition-all`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <code className="text-sm font-semibold text-gray-900 bg-gray-100 px-2 py-0.5 rounded">
                  {entry.name}
                </code>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full border ${getTypeColor(
                    entry.value
                  )}`}
                >
                  {getValueType(entry.value)}
                </span>
                <CopyButton text={entry.name} />
              </div>
              <pre className="mt-2 text-sm text-gray-700 whitespace-pre-wrap break-all bg-slate-50 p-3 rounded-md border border-slate-200 max-h-48 overflow-auto font-mono">
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

function SearchResultsTable({
  results,
  onHostClick,
}: {
  results: SearchResultEntry[];
  onHostClick: (host: string) => void;
}) {
  if (results.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">No results found</div>
    );
  }

  return (
    <div className="space-y-2">
      {results.map((result, index) => (
        <div
          key={`${result.host}-${result.name}-${index}`}
          className={`p-3 rounded-lg border ${
            index % 2 === 0
              ? "bg-white border-gray-200"
              : "bg-gray-50 border-gray-100"
          } hover:border-blue-300 hover:shadow-sm transition-all`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <button
                  onClick={() => onHostClick(result.host)}
                  className="text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                >
                  {result.host}
                </button>
                <span className="text-gray-400">/</span>
                <code className="text-sm font-semibold text-gray-900 bg-gray-100 px-2 py-0.5 rounded">
                  {result.name}
                </code>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full border ${getTypeColor(
                    result.value
                  )}`}
                >
                  {getValueType(result.value)}
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    result.source === "hostvars"
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-teal-100 text-teal-700"
                  }`}
                >
                  {result.source}
                </span>
              </div>
              <pre className="text-sm text-gray-700 whitespace-pre-wrap break-all bg-slate-50 p-3 rounded-md border border-slate-200 max-h-32 overflow-auto font-mono">
                {formatValue(result.value)}
              </pre>
            </div>
            <CopyButton text={formatValue(result.value)} />
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

  // Global search state
  const [showGlobalSearch, setShowGlobalSearch] = useState(false);
  const [globalNamePattern, setGlobalNamePattern] = useState("");
  const [globalHostPattern, setGlobalHostPattern] = useState("");
  const [globalSource, setGlobalSource] = useState<
    "hostvars" | "facts" | "all"
  >("all");
  const [searchTriggered, setSearchTriggered] = useState(false);

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

  // Global search query
  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
    refetch: refetchSearch,
  } = useQuery({
    queryKey: [
      "inventory-search",
      globalNamePattern,
      globalHostPattern,
      globalSource,
    ],
    queryFn: () =>
      api.inventory.search({
        name_pattern: globalNamePattern,
        host_pattern: globalHostPattern || undefined,
        source: globalSource === "all" ? undefined : globalSource,
        limit: 100,
      }),
    enabled: searchTriggered && globalNamePattern.length > 0,
    retry: false,
  });

  const filteredHosts =
    hostsData?.hosts.filter((host) =>
      host.toLowerCase().includes(hostSearchTerm.toLowerCase())
    ) || [];

  const handleSearch = () => {
    if (globalNamePattern.length > 0) {
      setSearchTriggered(true);
      refetchSearch();
    }
  };

  const handleHostClickFromSearch = (host: string) => {
    setSelectedHost(host);
    setShowGlobalSearch(false);
  };

  return (
    <div className="px-4 sm:px-0">
      <div className="sm:flex sm:items-center sm:justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Inventory</h2>
          <p className="mt-1 text-sm text-gray-600">
            View host variables and cached Ansible facts
          </p>
        </div>
        <div className="mt-4 sm:mt-0 flex gap-2">
          <button
            onClick={() => setShowGlobalSearch(!showGlobalSearch)}
            className={`inline-flex items-center px-4 py-2 border rounded-md shadow-sm text-sm font-medium transition-colors ${
              showGlobalSearch
                ? "border-blue-500 text-blue-700 bg-blue-50 hover:bg-blue-100"
                : "border-gray-300 text-gray-700 bg-white hover:bg-gray-50"
            } focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500`}
          >
            <Filter className="h-4 w-4 mr-2" />
            Global Search
          </button>
          <button
            onClick={() => {
              refetchHosts();
              if (selectedHost) {
                refetchHostvars();
                refetchFacts();
              }
            }}
            disabled={hostsRefetching}
            className="inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${hostsRefetching ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Global Search Panel */}
      {showGlobalSearch && (
        <div className="mb-6 bg-white shadow rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-gray-900 flex items-center gap-2">
              <Search className="h-5 w-5 text-gray-500" />
              Search Across All Hosts
            </h3>
            <button
              onClick={() => setShowGlobalSearch(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Variable/Fact Name Pattern (regex)
              </label>
              <input
                type="text"
                className="block w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                placeholder="e.g., ansible_.*ipv4.* or ^inventory_hostname$"
                value={globalNamePattern}
                onChange={(e) => {
                  setGlobalNamePattern(e.target.value);
                  setSearchTriggered(false);
                }}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Host Pattern (regex, optional)
              </label>
              <input
                type="text"
                className="block w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                placeholder="e.g., testbed-node-.*"
                value={globalHostPattern}
                onChange={(e) => {
                  setGlobalHostPattern(e.target.value);
                  setSearchTriggered(false);
                }}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Source
              </label>
              <select
                className="block w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                value={globalSource}
                onChange={(e) => {
                  setGlobalSource(
                    e.target.value as "hostvars" | "facts" | "all"
                  );
                  setSearchTriggered(false);
                }}
              >
                <option value="all">All</option>
                <option value="hostvars">Host Variables</option>
                <option value="facts">Facts (Cache)</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={handleSearch}
              disabled={!globalNamePattern || searchLoading}
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {searchLoading ? (
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Search className="h-4 w-4 mr-2" />
              )}
              Search
            </button>
            {searchData && (
              <span className="text-sm text-gray-600">
                Found {searchData.count} results across{" "}
                {searchData.hosts_searched} hosts
              </span>
            )}
          </div>

          {searchError && (
            <div className="mt-4 flex items-center text-red-600">
              <AlertCircle className="h-5 w-5 mr-2" />
              <span className="text-sm">
                Search failed:{" "}
                {searchError instanceof Error
                  ? searchError.message
                  : "Unknown error"}
              </span>
            </div>
          )}

          {searchData && searchData.results.length > 0 && (
            <div className="mt-4 max-h-[400px] overflow-y-auto">
              <SearchResultsTable
                results={searchData.results}
                onHostClick={handleHostClickFromSearch}
              />
            </div>
          )}

          {searchTriggered && searchData && searchData.results.length === 0 && (
            <div className="mt-4 text-center py-4 text-gray-500">
              No results found for the given pattern
            </div>
          )}
        </div>
      )}

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
