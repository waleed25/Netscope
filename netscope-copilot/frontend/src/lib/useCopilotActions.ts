import { useCopilotAction } from "@copilotkit/react-core";

const BASE_URL = "http://localhost:8001/api";

export const useNetScopeActions = () => {
  // Action: List Network Interfaces
  useCopilotAction({
    name: "listInterfaces",
    description: "List all available network interfaces on the system.",
    handler: async () => {
      const response = await fetch(`${BASE_URL}/interfaces`);
      const data = await response.json();
      return data.interfaces;
    },
  });

  // Action: Start Capture
  useCopilotAction({
    name: "startCapture",
    description: "Start a live packet capture on a specific network interface.",
    parameters: [
      {
        name: "interfaceName",
        type: "string",
        description: "The name of the interface to capture on (e.g., 'eth0', '\\Device\\NPF_...')",
        required: true,
      },
      {
        name: "filter",
        type: "string",
        description: "An optional BPF filter (e.g., 'tcp port 80')",
        required: false,
      },
    ],
    handler: async ({ interfaceName, filter }) => {
      const response = await fetch(`${BASE_URL}/capture/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interface: interfaceName, bpf_filter: filter || "" }),
      });
      return await response.json();
    },
  });

  // Action: Stop Capture
  useCopilotAction({
    name: "stopCapture",
    description: "Stop the currently running packet capture.",
    handler: async () => {
      const response = await fetch(`${BASE_URL}/capture/stop`, {
        method: "POST",
      });
      return await response.json();
    },
  });

  // Action: Expert Analysis
  useCopilotAction({
    name: "runExpertAnalysis",
    description: "Run an expert analysis mode on the captured packets.",
    parameters: [
      {
        name: "mode",
        type: "string",
        description: "The analysis mode: 'ics_audit', 'port_scan', 'flow_analysis', 'anomaly_detect'",
        required: true,
      }
    ],
    handler: async ({ mode }) => {
      const response = await fetch(`${BASE_URL}/expert/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, with_llm: true }),
      });
      return await response.json();
    },
  });
};
