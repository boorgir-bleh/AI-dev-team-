export const AGENT_ROLES = [
  "orchestrator",
  "architect",
  "developer",
  "cyber_security",
  "tester",
  "documentation",
  "critic",
] as const;

export type AgentRole = (typeof AGENT_ROLES)[number];

export interface AgentPromptConfig {
  name: string;
  system_prompt: string;
  task_prompt: string;
}

export interface AgentConfiguration {
  agents: Record<AgentRole, AgentPromptConfig>;
}

export const DEFAULT_AGENT_NAMES: Record<AgentRole, string> = {
  orchestrator: "Maya",
  architect: "Arjun",
  developer: "Dev",
  cyber_security: "Sana",
  tester: "Tara",
  documentation: "Doc",
  critic: "Ojas",
};

export const AGENT_LABELS: Record<AgentRole, string> = {
  orchestrator: "Orchestrator",
  architect: "Architect",
  developer: "Developer",
  cyber_security: "Cyber Security",
  tester: "Tester",
  documentation: "Documentation",
  critic: "Critic",
};

export const AGENT_COLORS: Record<AgentRole, string> = {
  orchestrator: "#78e7ee",
  architect: "#9f8cff",
  developer: "#55d6a8",
  cyber_security: "#ef7c92",
  tester: "#efc66f",
  documentation: "#77aef5",
  critic: "#ee9d63",
};
