"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Server, Settings } from "lucide-react";
import Link from "next/link";
import api from "@/lib/api";

export default function Home() {
  const { data: healthData, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: api.health.check,
    refetchInterval: 30000,
  });

  const { data: nodesData, isLoading: nodesLoading } = useQuery({
    queryKey: ["baremetal-nodes"],
    queryFn: api.baremetal.getNodes,
    refetchInterval: 60000,
  });

  const stats = [
    {
      name: "Total Nodes",
      value: nodesData?.count || 0,
      icon: Server,
      href: "/nodes",
      loading: nodesLoading,
    },
    {
      name: "Active Nodes",
      value: nodesData?.nodes.filter(n => n.provision_state === "active").length || 0,
      icon: Activity,
      href: "/nodes",
      loading: nodesLoading,
    },
    {
      name: "Services",
      value: "N/A",
      icon: Settings,
      href: "/services",
      loading: false,
    },
  ];

  return (
    <div className="px-4 sm:px-0">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>
        <p className="mt-1 text-sm text-gray-600">
          Overview of OSISM-managed infrastructure
        </p>
      </div>

      <div className="mb-8">
        <div className="inline-flex items-center">
          <span className="text-sm font-medium text-gray-700 mr-2">API Status:</span>
          {healthLoading ? (
            <span className="text-yellow-600">Checking...</span>
          ) : healthData?.result === "ok" ? (
            <span className="flex items-center text-green-600">
              <span className="h-2 w-2 bg-green-600 rounded-full mr-2"></span>
              Online
            </span>
          ) : (
            <span className="flex items-center text-red-600">
              <span className="h-2 w-2 bg-red-600 rounded-full mr-2"></span>
              Offline
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className="bg-white overflow-hidden shadow rounded-lg hover:shadow-md transition-shadow"
            >
              <div className="p-5">
                <div className="flex items-center">
                  <div className="flex-shrink-0">
                    <Icon className="h-6 w-6 text-gray-400" />
                  </div>
                  <div className="ml-5 w-0 flex-1">
                    <dl>
                      <dt className="text-sm font-medium text-gray-500 truncate">
                        {item.name}
                      </dt>
                      <dd className="text-lg font-semibold text-gray-900">
                        {item.loading ? (
                          <span className="text-gray-400">Loading...</span>
                        ) : (
                          item.value
                        )}
                      </dd>
                    </dl>
                  </div>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {nodesData && nodesData.nodes.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-medium text-gray-900 mb-4">
            Recent Nodes
          </h3>
          <div className="bg-white shadow overflow-hidden sm:rounded-md">
            <ul className="divide-y divide-gray-200">
              {nodesData.nodes.slice(0, 5).map((node) => (
                <li key={node.uuid}>
                  <div className="px-4 py-4 sm:px-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center">
                        <p className="text-sm font-medium text-gray-900">
                          {node.name || node.uuid}
                        </p>
                        <div className="ml-4 flex items-center space-x-2">
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            node.power_state === "power on" 
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            {node.power_state || "unknown"}
                          </span>
                          <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            node.provision_state === "active"
                              ? "bg-blue-100 text-blue-800"
                              : node.provision_state === "available"
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-800"
                          }`}>
                            {node.provision_state || "unknown"}
                          </span>
                        </div>
                      </div>
                      {node.maintenance && (
                        <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                          Maintenance
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}