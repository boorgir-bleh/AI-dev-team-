import { useEffect, useState } from "react";
import {
  AGENT_ROLES,
  type AgentConfiguration,
} from "../types/agents";

const STORAGE_KEY = "devoffice-agent-configuration";

function isAgentConfiguration(value: unknown): value is AgentConfiguration {
  if (!value || typeof value !== "object" || !("agents" in value)) return false;
  const agents = (value as { agents: unknown }).agents;
  if (!agents || typeof agents !== "object") return false;
  return AGENT_ROLES.every((role) => {
    const profile = (agents as Record<string, unknown>)[role];
    if (!profile || typeof profile !== "object") return false;
    const fields = profile as Record<string, unknown>;
    return ["name", "system_prompt", "task_prompt"].every(
      (field) => typeof fields[field] === "string",
    );
  });
}

function readSavedConfiguration(): { configuration: AgentConfiguration | null; error: string | null } {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { configuration: null, error: null };
    const value: unknown = JSON.parse(raw);
    if (isAgentConfiguration(value)) return { configuration: value, error: null };
    return { configuration: null, error: "Saved agent settings were invalid; defaults will be loaded." };
  } catch {
    return { configuration: null, error: "Saved agent settings could not be read; defaults will be loaded." };
  }
}

export function useAgentConfiguration() {
  const saved = readSavedConfiguration();
  const [configuration, setConfiguration] = useState<AgentConfiguration | null>(saved.configuration);
  const [defaults, setDefaults] = useState<AgentConfiguration | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(saved.error);

  useEffect(() => {
    let active = true;
    fetch("/api/agents/config")
      .then(async (response) => {
        if (!response.ok) throw new Error(`Could not load agent settings (${response.status}).`);
        return await response.json() as AgentConfiguration;
      })
      .then((loaded) => {
        if (!active) return;
        setDefaults(loaded);
        setConfiguration((current) => current ?? loaded);
        setError((current) => current?.startsWith("Saved agent settings") ? null : current);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load agent settings.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const save = (next: AgentConfiguration) => {
    setConfiguration(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setError(null);
    } catch {
      setError("Settings are active for this session, but could not be saved in this browser.");
    }
  };

  return { configuration, defaults, loading, error, setError, save };
}
