"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search, AlertCircle, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { BaremetalNode } from "@/lib/types";

export default function NodesPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterProvisionState, setFilterProvisionState] = useState("all");
  const [filterPowerState, setFilterPowerState] = useState("all");
  const [filterMaintenance, setFilterMaintenance] = useState("all");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["baremetal-nodes"],
    queryFn: api.baremetal.getNodes,
    refetchInterval: 60000,
  });

  const filteredAndSortedNodes = data?.nodes
    .filter((node: BaremetalNode) => {
      const matchesSearch = searchTerm === "" ||
        (node.name && node.name.toLowerCase().includes(searchTerm.toLowerCase())) ||
        (node.uuid && node.uuid.toLowerCase().includes(searchTerm.toLowerCase()));

      const matchesProvisionState = filterProvisionState === "all" ||
        node.provision_state === filterProvisionState;

      const matchesPowerState = filterPowerState === "all" ||
        node.power_state === filterPowerState;

      const matchesMaintenance = filterMaintenance === "all" ||
        (filterMaintenance === "maintenance" && node.maintenance === true) ||
        (filterMaintenance === "active" && node.maintenance === false);

      return matchesSearch && matchesProvisionState && matchesPowerState && matchesMaintenance;
    })
    .sort((a: BaremetalNode, b: BaremetalNode) => {
      const nameA = a.name || a.uuid || '';
      const nameB = b.name || b.uuid || '';

      if (sortDirection === "asc") {
        return nameA.localeCompare(nameB);
      } else {
        return nameB.localeCompare(nameA);
      }
    });

  const totalFilteredNodes = filteredAndSortedNodes?.length || 0;
  const totalPages = Math.ceil(totalFilteredNodes / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const paginatedNodes = filteredAndSortedNodes?.slice(startIndex, endIndex);

  // Reset to first page when filters change
  const resetToFirstPage = () => {
    setCurrentPage(1);
  };

  const toggleSortDirection = () => {
    setSortDirection(prev => prev === "asc" ? "desc" : "asc");
  };

  const uniqueProvisionStates = data ?
    [...new Set(data.nodes.map(n => n.provision_state).filter((state): state is string => Boolean(state)))] : [];

  const uniquePowerStates = data ?
    [...new Set(data.nodes.map(n => n.power_state).filter((state): state is string => Boolean(state)))] : [];

  return (
    <div className="px-4 sm:px-0">
      <div className="sm:flex sm:items-center sm:justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Baremetal Nodes</h2>
          <p className="mt-1 text-sm text-gray-600">
            Management and monitoring of all baremetal nodes
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isRefetching}
          className="mt-4 sm:mt-0 inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="bg-white shadow rounded-lg mb-6">
        <div className="px-4 py-5 sm:p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <div>
              <label htmlFor="search" className="block text-sm font-medium text-gray-700">
                Search
              </label>
              <div className="mt-1 relative rounded-md shadow-sm">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Search className="h-4 w-4 text-gray-400" />
                </div>
                <input
                  type="text"
                  name="search"
                  id="search"
                  className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 pr-3 py-2 sm:text-sm border-gray-300 rounded-md"
                  placeholder="Name or UUID..."
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value);
                    resetToFirstPage();
                  }}
                />
              </div>
            </div>

            <div>
              <label htmlFor="provision-state" className="block text-sm font-medium text-gray-700">
                Provision State
              </label>
              <select
                id="provision-state"
                name="provision-state"
                className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                value={filterProvisionState}
                onChange={(e) => {
                  setFilterProvisionState(e.target.value);
                  resetToFirstPage();
                }}
              >
                <option value="all">All</option>
                {uniqueProvisionStates.map((state, index) => (
                  <option key={`provision-${state}-${index}`} value={state}>{state}</option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="power-state" className="block text-sm font-medium text-gray-700">
                Power State
              </label>
              <select
                id="power-state"
                name="power-state"
                className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                value={filterPowerState}
                onChange={(e) => {
                  setFilterPowerState(e.target.value);
                  resetToFirstPage();
                }}
              >
                <option value="all">All</option>
                {uniquePowerStates.map((state, index) => (
                  <option key={`power-${state}-${index}`} value={state}>{state}</option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="maintenance-state" className="block text-sm font-medium text-gray-700">
                Maintenance
              </label>
              <select
                id="maintenance-state"
                name="maintenance-state"
                className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                value={filterMaintenance}
                onChange={(e) => {
                  setFilterMaintenance(e.target.value);
                  resetToFirstPage();
                }}
              >
                <option value="all">All</option>
                <option value="active">Active</option>
                <option value="maintenance">Maintenance</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-6">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-red-400" />
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">
                Error loading nodes
              </h3>
              <div className="mt-2 text-sm text-red-700">
                <p>Failed to load nodes. Please check the API connection.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <div className="px-4 py-5 sm:p-6">
            <div className="animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-1/4 mb-4"></div>
              <div className="space-y-3">
                <div className="h-4 bg-gray-200 rounded"></div>
                <div className="h-4 bg-gray-200 rounded"></div>
                <div className="h-4 bg-gray-200 rounded"></div>
              </div>
            </div>
          </div>
        </div>
      ) : paginatedNodes && paginatedNodes.length > 0 ? (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <div className="flex items-center">
              <button
                onClick={toggleSortDirection}
                className="flex items-center text-sm font-medium text-gray-700 hover:text-gray-900"
              >
                Name
                <ArrowUpDown className="ml-1 h-4 w-4" />
                <span className="ml-1 text-xs text-gray-500">
                  ({sortDirection === "asc" ? "A-Z" : "Z-A"})
                </span>
              </button>
            </div>
          </div>
          <ul className="divide-y divide-gray-200">
            {paginatedNodes.map((node: BaremetalNode, index) => (
              <li key={node.uuid || `node-${index}`}>
                <div className="px-4 py-4 sm:px-6">
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center">
                          <p className="text-sm font-medium text-gray-900">
                            {node.name || node.uuid}
                          </p>
                          {node.maintenance && (
                            <span className="ml-2 px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                              Maintenance
                            </span>
                          )}
                        </div>
                        <div className="flex items-center justify-end gap-2">
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            node.power_state === "power on"
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            Power: {node.power_state || "unknown"}
                          </span>
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            node.provision_state === "active"
                              ? "bg-blue-100 text-blue-800"
                              : node.provision_state === "available"
                              ? "bg-green-100 text-green-800"
                              : node.provision_state === "deploying"
                              ? "bg-yellow-100 text-yellow-800"
                              : node.provision_state === "error"
                              ? "bg-red-100 text-red-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            Provision: {node.provision_state || "unknown"}
                          </span>
                        </div>
                      </div>
                      <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
                        <p className="flex items-center text-sm text-gray-500 lg:col-span-2">
                          UUID: {node.uuid}
                        </p>
                        {node.driver && (
                          <p className="flex items-center text-sm text-gray-500">
                            Driver: {node.driver}
                          </p>
                        )}
                        {node.created_at && (
                          <p className="flex items-center justify-end text-sm text-gray-500">
                            Created: {new Date(node.created_at).toLocaleString()}
                          </p>
                        )}
                        {node.updated_at && (
                          <p className="flex items-center justify-end text-sm text-gray-500 lg:col-start-4">
                            Updated: {new Date(node.updated_at).toLocaleString()}
                          </p>
                        )}
                      </div>
                      {node.last_error && (
                        <div className="mt-2">
                          <p className="text-sm text-red-600">
                            Error: {node.last_error}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <div className="px-4 py-5 sm:p-6 text-center">
            <p className="text-gray-500">No nodes found</p>
          </div>
        </div>
      )}

      {data && totalFilteredNodes > 0 && (
        <div className="mt-6">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm text-gray-600">
              Showing {startIndex + 1} to {Math.min(endIndex, totalFilteredNodes)} of {totalFilteredNodes} filtered nodes
              {totalFilteredNodes !== data.count && (
                <span className="text-gray-500"> ({data.count} total)</span>
              )}
            </div>
            {totalPages > 1 && (
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="inline-flex items-center px-3 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4 mr-1" />
                  Previous
                </button>

                <div className="flex items-center space-x-1">
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter(page => {
                      // Show first page, last page, current page, and pages around current
                      return page === 1 ||
                             page === totalPages ||
                             Math.abs(page - currentPage) <= 1;
                    })
                    .map((page, index, array) => {
                      // Add ellipsis if there's a gap
                      const showEllipsisBefore = index > 0 && page - array[index - 1] > 1;
                      return (
                        <div key={page} className="flex items-center">
                          {showEllipsisBefore && (
                            <span className="px-2 py-1 text-gray-500">...</span>
                          )}
                          <button
                            onClick={() => setCurrentPage(page)}
                            className={`px-3 py-2 text-sm font-medium rounded-md ${
                              currentPage === page
                                ? "bg-blue-500 text-white"
                                : "text-gray-700 bg-white border border-gray-300 hover:bg-gray-50"
                            } focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500`}
                          >
                            {page}
                          </button>
                        </div>
                      );
                    })
                  }
                </div>

                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="inline-flex items-center px-3 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                  <ChevronRight className="h-4 w-4 ml-1" />
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}