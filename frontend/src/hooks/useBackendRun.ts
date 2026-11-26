import { useRef, useState } from "react";
import type { AgentConfiguration } from "../types/agents";
import type { EventEnvelope } from "../types/events";

type RunStatus = "idle" | "starting" | "connecting" | "running" | "completed" | "failed" | "disconnected";

interface StartRunResponse {
  run_id: string;
  status: string;
  provider: string;
  model: string;
}

export function useBackendRun() {
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const start = async (prompt: string, agentConfiguration: AgentConfiguration) => {
    socketRef.current?.close();
    setEvents([]);
    setRunId(null);
    setProvider(null);
    setModel(null);
    setError(null);
    setStatus("starting");

    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, agent_configuration: agentConfiguration }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(typeof detail?.detail === "string" ? detail.detail : `Run request failed (${response.status}).`);
      }

      const started = await response.json() as StartRunResponse;
      setRunId(started.run_id);
      setProvider(started.provider);
      setModel(started.model);
      setStatus("connecting");

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/ws/${started.run_id}`);
      socketRef.current = socket;
      socket.onopen = () => setStatus((current) => current === "connecting" ? "running" : current);
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as EventEnvelope;
          setEvents((current) => [...current, event]);
          if (event.type === "run_complete") {
            setStatus("completed");
            socket.close(1000, "Run completed");
          } else if (event.type === "error") {
            setError(String(event.payload.message ?? "The run failed."));
            setStatus("failed");
            socket.close(1011, "Run failed");
          }
        } catch {
          setError("The server sent an event that could not be read.");
          setStatus("failed");
          socket.close(1007, "Invalid event");
        }
      };
      socket.onerror = () => {
        setError("Could not connect to the event stream. Check that the backend is running.");
        setStatus("failed");
      };
      socket.onclose = () => {
        setStatus((current) => current === "running" || current === "connecting" ? "disconnected" : current);
      };
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the run.");
      setStatus("failed");
    }
  };

  return { events, runId, provider, model, status, error, start };
}
