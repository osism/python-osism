"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Server } from "lucide-react";
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

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        {stats.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              href={item.href}
              className="bg-white overflow-hidden shadow rounded-lg hover:shadow-md transition-shadow"
            >
              <div className="px-8 py-12">
                <div className="flex flex-col items-center text-center">
                  <Icon className="h-12 w-12 text-gray-400 mb-4" />
                  <dl>
                    <dt className="text-lg font-medium text-gray-500">
                      {item.name}
                    </dt>
                    <dd className="mt-2 text-5xl font-bold text-gray-900">
                      {item.loading ? (
                        <span className="text-gray-400">...</span>
                      ) : (
                        item.value
                      )}
                    </dd>
                  </dl>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

    </div>
  );
}