"use client";

import { AlertCircle } from "lucide-react";

export default function ServicesPage() {
  return (
    <div className="px-4 sm:px-0">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Services</h2>
        <p className="mt-1 text-sm text-gray-600">
          Monitoring and management of OSISM services
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
        <div className="flex">
          <AlertCircle className="h-5 w-5 text-blue-400" />
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800">
              Services API in Development
            </h3>
            <div className="mt-2 text-sm text-blue-700">
              <p>
                Services functionality will be implemented once the corresponding
                API endpoints are available in the OSISM FastAPI.
              </p>
              <p className="mt-2">
                Planned features:
              </p>
              <ul className="list-disc list-inside mt-1">
                <li>Overview of all OSISM services</li>
                <li>Service status monitoring</li>
                <li>Service configuration</li>
                <li>Start/Stop/Restart operations</li>
                <li>Log viewing</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}