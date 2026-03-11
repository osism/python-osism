"use client";

import { use, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, RefreshCw, AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { BaremetalNode, BaremetalPort } from "@/lib/types";
import CopyButton from "@/app/components/CopyButton";

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function NodeDetailPage({ params }: { params: Promise<{ identifier: string }> }) {
  const { identifier } = use(params);
  const decodedIdentifier = decodeURIComponent(identifier);
  const isUuid = UUID_REGEX.test(decodedIdentifier);

  const { data: nodesData, isLoading: nodesLoading, error: nodesError } = useQuery({
    queryKey: ["baremetal-nodes"],
    queryFn: api.baremetal.getNodes,
    refetchInterval: 60000,
  });

  const matchingNodes = useMemo(() => {
    if (!nodesData) return [];
    if (isUuid) {
      const node = nodesData.nodes.find((n: BaremetalNode) => n.uuid === decodedIdentifier);
      return node ? [node] : [];
    }
    return nodesData.nodes.filter((n: BaremetalNode) => n.name === decodedIdentifier);
  }, [nodesData, decodedIdentifier, isUuid]);

  const node = matchingNodes.length === 1 ? matchingNodes[0] : null;
  const nodeUuid = node?.uuid;

  const { data: netboxData } = useQuery({
    queryKey: ["baremetal-netbox-node", node?.name],
    queryFn: () => api.baremetal.getNodeNetboxInfo(node!.name!),
    enabled: !!node?.name,
  });

  const { data: portsData, isLoading: portsLoading, error: portsError, refetch, isRefetching } = useQuery({
    queryKey: ["baremetal-node-ports", nodeUuid],
    queryFn: () => api.baremetal.getNodePorts(nodeUuid!),
    enabled: !!nodeUuid,
    refetchInterval: 60000,
  });

  const { data: paramsData } = useQuery({
    queryKey: ["baremetal-node-parameters", nodeUuid],
    queryFn: () => api.baremetal.getNodeParameters(nodeUuid!),
    enabled: !!nodeUuid,
    refetchInterval: 60000,
  });

  const isLoading = nodesLoading || (!!nodeUuid && portsLoading);

  // Multiple nodes match the name - show selection list
  if (!nodesLoading && matchingNodes.length > 1) {
    return (
      <div className="px-4 sm:px-0">
        <div className="mb-6">
          <Link
            href="/nodes"
            className="inline-flex items-center text-sm text-gray-500 hover:text-gray-700 mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Nodes
          </Link>
          <h2 className="text-2xl font-bold text-gray-900">
            Multiple nodes found for &quot;{decodedIdentifier}&quot;
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            {matchingNodes.length} nodes match this name. Please select one.
          </p>
        </div>
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {matchingNodes.map((n: BaremetalNode) => (
              <li key={n.uuid}>
                <Link href={`/nodes/${n.uuid}`} className="block hover:bg-gray-50">
                  <div className="px-4 py-4 sm:px-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center min-w-0">
                        <p className="text-sm font-medium text-blue-600 truncate">
                          {n.name || n.uuid}
                        </p>
                      </div>
                      <div className="ml-4 flex items-center gap-2">
                        {n.provision_state && (
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            n.provision_state === "active"
                              ? "bg-blue-100 text-blue-800"
                              : n.provision_state === "available"
                              ? "bg-green-100 text-green-800"
                              : n.provision_state === "error"
                              ? "bg-red-100 text-red-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            {n.provision_state}
                          </span>
                        )}
                        {n.power_state && (
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            n.power_state === "power on"
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            {n.power_state}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="mt-2">
                      <p className="text-sm text-gray-500">
                        UUID: {n.uuid}
                      </p>
                      {n.conductor && (
                        <p className="text-sm text-gray-500">
                          Conductor: {n.conductor}
                        </p>
                      )}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-0">
      <div className="mb-6">
        <Link
          href="/nodes"
          className="inline-flex items-center text-sm text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to Nodes
        </Link>
        <div className="sm:flex sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-1">
              {node?.name || decodedIdentifier}
              {node?.name && <CopyButton text={node.name} />}
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              Node details and ports
            </p>
          </div>
          {node && (
            <button
              onClick={() => refetch()}
              disabled={isRefetching}
              className="mt-4 sm:mt-0 inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          )}
        </div>
      </div>

      {(nodesError || portsError) && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-6">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-red-400" />
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">Error loading data</h3>
              <div className="mt-2 text-sm text-red-700">
                <p>Failed to load node details. Please check the API connection.</p>
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
      ) : node ? (
        <>
          <div className="bg-white shadow overflow-hidden sm:rounded-lg mb-6">
            <div className="px-4 py-5 sm:px-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900">Node Information</h3>
            </div>
            <div className="border-t border-gray-200">
              <dl>
                <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">Name</dt>
                  <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                    {node.name || "-"}
                    {node.name && <CopyButton text={node.name} />}
                  </dd>
                </div>
                <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">UUID</dt>
                  <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                    {node.uuid}
                    <CopyButton text={node.uuid} />
                  </dd>
                </div>
                <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">Device Role</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2">
                    {netboxData?.device_role ? (
                      <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-purple-100 text-purple-800">
                        {netboxData.device_role}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-500">-</span>
                    )}
                  </dd>
                </div>
                {netboxData?.primary_ip4 && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Primary IPv4</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                      {netboxData.primary_ip4}
                      <CopyButton text={netboxData.primary_ip4} />
                    </dd>
                  </div>
                )}
                {netboxData?.primary_ip6 && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Primary IPv6</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                      {netboxData.primary_ip6}
                      <CopyButton text={netboxData.primary_ip6} />
                    </dd>
                  </div>
                )}
                <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">Power State</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2">
                    <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                      node.power_state === "power on"
                        ? "bg-green-100 text-green-800"
                        : "bg-gray-100 text-gray-800"
                    }`}>
                      {node.power_state || "unknown"}
                    </span>
                  </dd>
                </div>
                <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">Provision State</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2">
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
                      {node.provision_state || "unknown"}
                    </span>
                  </dd>
                </div>
                <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">Maintenance</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2">
                    {node.maintenance ? (
                      <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                        Maintenance
                      </span>
                    ) : (
                      <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">
                        Active
                      </span>
                    )}
                  </dd>
                </div>
                {node.maintenance && node.maintenance_reason && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Maintenance Reason</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.maintenance_reason}</dd>
                  </div>
                )}
                {node.fault && (
                  <div className="bg-red-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-red-500">Fault</dt>
                    <dd className="mt-1 sm:mt-0 sm:col-span-2">
                      <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800">
                        {node.fault}
                      </span>
                    </dd>
                  </div>
                )}
                {node.driver && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Driver</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.driver}</dd>
                  </div>
                )}
                {node.redfish_address && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Redfish Address</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                      <a
                        href={node.redfish_address}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:text-blue-800 hover:underline"
                      >
                        {node.redfish_address}
                      </a>
                      <CopyButton text={node.redfish_address} />
                    </dd>
                  </div>
                )}
                {node.resource_class && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Resource Class</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.resource_class}</dd>
                  </div>
                )}
                {node.conductor && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Conductor</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.conductor}</dd>
                  </div>
                )}
                {node.description && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Description</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.description}</dd>
                  </div>
                )}
                {node.owner && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Owner</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.owner}</dd>
                  </div>
                )}
                {node.lessee && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Lessee</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.lessee}</dd>
                  </div>
                )}
                {node.traits && node.traits.length > 0 && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Traits</dt>
                    <dd className="mt-1 sm:mt-0 sm:col-span-2 flex flex-wrap gap-1">
                      {node.traits.map((trait) => (
                        <span key={trait} className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-indigo-100 text-indigo-800">
                          {trait}
                        </span>
                      ))}
                    </dd>
                  </div>
                )}
                {node.instance_uuid && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Instance UUID</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.instance_uuid}</dd>
                  </div>
                )}
                {node.allocation_uuid && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Allocation UUID</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{node.allocation_uuid}</dd>
                  </div>
                )}
                {node.provision_updated_at && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Provision Updated</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{new Date(node.provision_updated_at).toLocaleString()}</dd>
                  </div>
                )}
                {node.created_at && (
                  <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Created</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{new Date(node.created_at).toLocaleString()}</dd>
                  </div>
                )}
                {node.updated_at && (
                  <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Updated</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">{new Date(node.updated_at).toLocaleString()}</dd>
                  </div>
                )}
                {node.last_error && (
                  <div className="bg-red-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-red-500">Last Error</dt>
                    <dd className="mt-1 text-sm text-red-700 sm:mt-0 sm:col-span-2 flex items-center gap-1">
                      {node.last_error}
                      <CopyButton text={node.last_error} />
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          </div>

          {(paramsData && (paramsData.kernel_append_params || paramsData.netplan_parameters || paramsData.frr_parameters)) || (node.properties && Object.keys(node.properties).length > 0) ? (
            <div className="bg-white shadow overflow-hidden sm:rounded-lg mb-6">
              <div className="px-4 py-5 sm:px-6">
                <h3 className="text-lg leading-6 font-medium text-gray-900">Parameters</h3>
              </div>
              <div className="border-t border-gray-200">
                <dl>
                  {node.properties && Object.keys(node.properties).length > 0 && (
                    <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                      <dt className="text-sm font-medium text-gray-500">Properties</dt>
                      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(node.properties).map(([key, value]) => (
                            <span
                              key={key}
                              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                            >
                              <span className="font-semibold">{key}</span>
                              <span className="mx-0.5">=</span>
                              <span>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                            </span>
                          ))}
                        </div>
                      </dd>
                    </div>
                  )}
                  {paramsData?.kernel_append_params && (
                    <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                      <dt className="text-sm font-medium text-gray-500">Kernel Append Params</dt>
                      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                        <div className="flex flex-wrap gap-1">
                          {paramsData.kernel_append_params.split(" ").map((param, i) => {
                            const [key, value] = param.split("=", 2);
                            const isSecret = value === "***";
                            return (
                              <span
                                key={i}
                                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                                  isSecret
                                    ? "bg-red-100 text-red-800"
                                    : "bg-gray-100 text-gray-800"
                                }`}
                              >
                                {value !== undefined ? (
                                  <>
                                    <span className="font-semibold">{key}</span>
                                    <span className="mx-0.5">=</span>
                                    <span>{value}</span>
                                  </>
                                ) : (
                                  <span>{param}</span>
                                )}
                              </span>
                            );
                          })}
                        </div>
                      </dd>
                    </div>
                  )}
                  {paramsData?.netplan_parameters && (
                    <div className="bg-white px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                      <dt className="text-sm font-medium text-gray-500">Netplan Parameters</dt>
                      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                        <pre className="bg-gray-50 rounded p-3 overflow-x-auto text-xs">
                          {JSON.stringify(paramsData.netplan_parameters, null, 2)}
                        </pre>
                      </dd>
                    </div>
                  )}
                  {paramsData?.frr_parameters && (
                    <div className="bg-gray-50 px-4 py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                      <dt className="text-sm font-medium text-gray-500">FRR Parameters</dt>
                      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                        <pre className="bg-white rounded p-3 overflow-x-auto text-xs">
                          {JSON.stringify(paramsData.frr_parameters, null, 2)}
                        </pre>
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            </div>
          ) : null}

          <div className="bg-white shadow overflow-hidden sm:rounded-lg">
            <div className="px-4 py-5 sm:px-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900">
                Ports
                {portsData && (
                  <span className="ml-2 text-sm font-normal text-gray-500">
                    ({portsData.count})
                  </span>
                )}
              </h3>
            </div>
            {portsData && portsData.ports.length > 0 ? (
              <div className="border-t border-gray-200">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        MAC Address
                      </th>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        UUID
                      </th>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        PXE Enabled
                      </th>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Created
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {portsData.ports.map((port: BaremetalPort, index) => (
                      <tr key={port.uuid || `port-${index}`}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          {port.address || "-"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {port.uuid}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {port.pxe_enabled === null ? "-" : port.pxe_enabled ? "Yes" : "No"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {port.created_at ? new Date(port.created_at).toLocaleString() : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="border-t border-gray-200 px-4 py-5 sm:p-6 text-center">
                <p className="text-gray-500">No ports found for this node</p>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <div className="px-4 py-5 sm:p-6 text-center">
            <p className="text-gray-500">Node not found</p>
          </div>
        </div>
      )}
    </div>
  );
}
