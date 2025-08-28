"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Server, Settings, Zap } from "lucide-react";
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
      id: "total-nodes",
      name: "Total Nodes",
      value: nodesData?.count || 0,
      icon: Server,
      href: "/nodes",
      loading: nodesLoading,
    },
    {
      id: "active-nodes",
      name: "Active Nodes",
      value: nodesData?.nodes.filter(n => n.provision_state === "active").length || 0,
      icon: Activity,
      href: "/nodes",
      loading: nodesLoading,
    },
    {
      id: "services",
      name: "Services",
      value: "N/A",
      icon: Settings,
      href: "/services",
      loading: false,
    },
    {
      id: "events",
      name: "Live Events",
      value: "Stream",
      icon: Zap,
      href: "/events",
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
              key={item.id}
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

    </div>
  );
}