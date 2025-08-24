"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search, AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { BaremetalNode } from "@/lib/types";

export default function NodesPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterProvisionState, setFilterProvisionState] = useState("all");
  const [filterPowerState, setFilterPowerState] = useState("all");
  const [filterMaintenance, setFilterMaintenance] = useState("all");

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["baremetal-nodes"],
    queryFn: api.baremetal.getNodes,
    refetchInterval: 60000,
  });

  const filteredNodes = data?.nodes.filter((node: BaremetalNode) => {
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
  });

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
                  onChange={(e) => setSearchTerm(e.target.value)}
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
                onChange={(e) => setFilterProvisionState(e.target.value)}
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
                onChange={(e) => setFilterPowerState(e.target.value)}
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
                onChange={(e) => setFilterMaintenance(e.target.value)}
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
      ) : filteredNodes && filteredNodes.length > 0 ? (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {filteredNodes.map((node: BaremetalNode, index) => (
              <li key={node.uuid || `node-${index}`}>
                <div className="px-4 py-4 sm:px-6">
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
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
                      <div className="mt-2 sm:flex sm:justify-between">
                        <div className="sm:flex">
                          <p className="flex items-center text-sm text-gray-500">
                            UUID: {node.uuid}
                          </p>
                          {node.driver && (
                            <p className="mt-2 flex items-center text-sm text-gray-500 sm:mt-0 sm:ml-6">
                              Driver: {node.driver}
                            </p>
                          )}
                          {node.resource_class && (
                            <p className="mt-2 flex items-center text-sm text-gray-500 sm:mt-0 sm:ml-6">
                              Resource Class: {node.resource_class}
                            </p>
                          )}
                        </div>
                        <div className="mt-2 flex items-center text-sm sm:mt-0">
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            node.power_state === "power on" 
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            Power: {node.power_state || "unknown"}
                          </span>
                          <span className={`ml-2 px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
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

      {data && (
        <div className="mt-4 text-sm text-gray-600">
          Showing {filteredNodes?.length || 0} of {data.count} nodes
        </div>
      )}
    </div>
  );
}