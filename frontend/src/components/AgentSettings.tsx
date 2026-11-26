import { useEffect, useState } from "react";
import {
  AGENT_LABELS,
  AGENT_ROLES,
  type AgentConfiguration,
  type AgentRole,
} from "../types/agents";

interface AgentSettingsProps {
  open: boolean;
  configuration: AgentConfiguration | null;
  defaults: AgentConfiguration | null;
  settingsError: string | null;
  onClose: () => void;
  onSave: (configuration: AgentConfiguration) => void;
  onReset: () => void;
}

export default function AgentSettings({
  open,
  configuration,
  defaults,
  settingsError,
  onClose,
  onSave,
  onReset,
}: AgentSettingsProps) {
  const [selectedRole, setSelectedRole] = useState<AgentRole>("orchestrator");
  const [draft, setDraft] = useState<AgentConfiguration | null>(configuration);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(configuration);
      setValidationError(null);
    }
  }, [open, configuration]);

  if (!open) return null;
  const profile = draft?.agents[selectedRole];

  const updateProfile = (field: "name" | "system_prompt" | "task_prompt", value: string) => {
    if (!draft) return;
    setDraft({
      ...draft,
      agents: {
        ...draft.agents,
        [selectedRole]: { ...draft.agents[selectedRole], [field]: value },
      },
    });
    setValidationError(null);
  };

  const save = () => {
    if (!draft) return;
    if (AGENT_ROLES.some((role) => !draft.agents[role].name.trim() ||
      !draft.agents[role].system_prompt.trim() || !draft.agents[role].task_prompt.trim())) {
      setValidationError("Names and both prompt fields are required for every agent.");
      return;
    }
    const names = AGENT_ROLES.map((role) => draft.agents[role].name.trim().toLocaleLowerCase());
    if (new Set(names).size !== names.length) {
      setValidationError("Each agent needs a unique name.");
      return;
    }
    onSave(draft);
    onClose();
  };

  return (
    <div className="settings-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-settings-title"
      >
        <header className="settings-heading">
          <div>
            <span className="section-kicker">MAKE IT YOUR TEAM</span>
            <h2 id="agent-settings-title">Agent settings</h2>
            <p>Names and prompts are saved in this browser and sent with each run.</p>
          </div>
          <button type="button" className="settings-close" aria-label="Close settings" onClick={onClose}>×</button>
        </header>
        {!draft || !profile ? (
          <p className="settings-error">Agent settings are not available yet. Check the backend connection.</p>
        ) : (
          <>
            <div className="settings-content">
              <nav className="settings-agent-list" aria-label="Choose an agent">
                {AGENT_ROLES.map((role) => (
                  <button
                    type="button"
                    key={role}
                    className={selectedRole === role ? "active" : ""}
                    onClick={() => setSelectedRole(role)}
                  >
                    <span>{draft.agents[role].name || AGENT_LABELS[role]}</span>
                    <small>{AGENT_LABELS[role]}</small>
                  </button>
                ))}
              </nav>
              <div className="settings-fields">
                <label>
                  Display name
                  <input
                    value={profile.name}
                    maxLength={80}
                    onChange={(event) => updateProfile("name", event.target.value)}
                  />
                </label>
                <label>
                  System prompt
                  <textarea
                    value={profile.system_prompt}
                    maxLength={20_000}
                    rows={9}
                    onChange={(event) => updateProfile("system_prompt", event.target.value)}
                  />
                </label>
                <label>
                  Task prompt
                  <textarea
                    value={profile.task_prompt}
                    maxLength={10_000}
                    rows={7}
                    onChange={(event) => updateProfile("task_prompt", event.target.value)}
                  />
                </label>
                <p className="settings-hint">
                  In task prompts, <code>{"{{context}}"}</code> is replaced by the run data.
                  If omitted, the data is appended automatically. Use <code>{"{{agent_name}}"}</code> in either prompt.
                </p>
              </div>
            </div>
            {validationError && <p className="settings-error">{validationError}</p>}
            {settingsError && <p className="settings-error">{settingsError}</p>}
            <footer className="settings-actions">
              <button type="button" className="settings-reset" disabled={!defaults} onClick={onReset}>
                Restore defaults
              </button>
              <div>
                <button type="button" className="settings-cancel" onClick={onClose}>Cancel</button>
                <button type="button" className="settings-save" onClick={save}>Save settings</button>
              </div>
            </footer>
          </>
        )}
      </section>
    </div>
  );
}
