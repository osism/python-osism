"use client";

import { Wifi, WifiOff, AlertCircle } from "lucide-react";
import { ConnectionStatus as ConnectionStatusType } from "@/lib/types";
import { formatDistanceToNow } from "date-fns";

interface ConnectionStatusProps {
  status: ConnectionStatusType;
  className?: string;
}

export default function ConnectionStatus({ status, className = "" }: ConnectionStatusProps) {
  const getStatusContent = () => {
    if (status.connected) {
      return {
        icon: Wifi,
        text: "Connected",
        color: "text-green-600",
        bgColor: "bg-green-100",
      };
    } else if (status.error) {
      return {
        icon: AlertCircle,
        text: `Disconnected: ${status.error}`,
        color: "text-red-600",
        bgColor: "bg-red-100",
      };
    } else {
      return {
        icon: WifiOff,
        text: "Disconnected",
        color: "text-gray-600",
        bgColor: "bg-gray-100",
      };
    }
  };

  const { icon: Icon, text, color, bgColor } = getStatusContent();

  return (
    <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${bgColor} ${color} ${className}`}>
      <Icon className="h-4 w-4 mr-2" />
      <span>{text}</span>
      {status.lastConnected && !status.connected && (
        <span className="ml-2 text-xs opacity-75">
          (Last: {formatDistanceToNow(status.lastConnected)} ago)
        </span>
      )}
    </div>
  );
}