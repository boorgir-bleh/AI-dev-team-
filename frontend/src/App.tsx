import { useState } from "react";
import AgentSettings from "./components/AgentSettings";
import OfficeView from "./components/OfficeView";
import { SchedulePanel, TranscriptPanel, UpdatesPanel } from "./components/Panels";
import { useAgentConfiguration } from "./hooks/useAgentConfiguration";
import { useBackendRun } from "./hooks/useBackendRun";
import { useMockReplay } from "./hooks/useMockReplay";
import {
  AGENT_LABELS,
  AGENT_ROLES,
  DEFAULT_AGENT_NAMES,
  type AgentRole,
} from "./types/agents";

const tasks: Record<AgentRole, string> = {
  orchestrator: "Turning the prompt into acceptance criteria",
  architect: "Preparing component and interface design",
  developer: "Implementing the approved design",
  cyber_security: "Checking the design and code for security risk",
  tester: "Mapping tests to acceptance criteria",
  documentation: "Writing setup and usage documentation",
  critic: "Reviewing quality and spec alignment",
};

export default function App() {
  const [speed, setSpeed] = useState(1);
  const [selectedAgent, setSelectedAgent] = useState<AgentRole | null>("orchestrator");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [prompt, setPrompt] = useState(
    "Build a CLI tool that converts CSV files to JSON with schema validation.",
  );
  const [mode, setMode] = useState<"demo" | "live">("demo");
  const agentSettings = useAgentConfiguration();
  const names: Record<AgentRole, string> = { ...DEFAULT_AGENT_NAMES };
  AGENT_ROLES.forEach((role) => {
    names[role] = agentSettings.configuration?.agents[role].name ?? DEFAULT_AGENT_NAMES[role];
  });
  const replay = useMockReplay(speed, names);
  const liveRun = useBackendRun();
  const events = mode === "live" ? liveRun.events : replay.events;
  const runId = mode === "live" ? liveRun.runId ?? "new run" : replay.runId;
  const isLiveRunning = ["starting", "connecting", "running"].includes(liveRun.status);

  const latestMilestone = [...events].reverse().find((event) => event.type === "milestone_update");
  const stage = String(latestMilestone?.payload.stage ?? "Getting started");
  const stageMatch = stage.match(/(\d+)\s+of\s+(\d+)/);
  const progress = mode === "demo"
    ? Math.round((replay.cursor / replay.total) * 100)
    : stageMatch
      ? Math.round((Number(stageMatch[1]) / Number(stageMatch[2])) * 100)
      : liveRun.status === "completed" ? 100 : 0;

  const latestArtifact = [...events].reverse().find((event) => event.type === "artifact_created");
  const activeTask = selectedAgent
    ? [...events]
        .reverse()
        .find((event) =>
          (event.payload.agent_role === selectedAgent || event.agent === names[selectedAgent]) &&
          event.type === "agent_status",
        )?.payload.activity
    : null;

  return (
    <main className="app">
      <header className="top-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 36 36">
              <path d="M7 27V9h8c6 0 10 3 10 9s-4 9-10 9H7Zm5-4h3c3 0 5-2 5-5s-2-5-5-5h-3v10Z" fill="currentColor" />
              <path d="M27 8v20" stroke="#bd7c5e" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <strong>DevOffice</strong>
            <span>A small team, at work</span>
          </div>
        </div>
        <div className="run-context">
          <span className="demo-tag"><i /> {mode === "demo" ? "DEMO RUN" : (liveRun.provider ?? "LIVE RUN").toUpperCase()}</span>
          <span className="run-id">{runId}</span>
        </div>
        <div className="controls">
          <button
            type="button"
            className="control-button"
            onClick={() => setSettingsOpen(true)}
          >
            Agent settings
          </button>
          <button
            onClick={() => replay.setPlaying(!replay.playing)}
            className="control-button primary-control"
            disabled={mode === "live" || replay.cursor >= replay.total}
          >
            {mode === "live"
              ? (isLiveRunning ? "Working…" : liveRun.status === "completed" ? "Finished" : "Live run")
              : (replay.cursor >= replay.total ? "Finished" : replay.playing ? "Pause" : "Continue")}
          </button>
          <button
            onClick={() => {
              replay.replay();
              setMode("demo");
            }}
            className="control-button"
          >
            Watch demo
          </button>
          <label>
            Pace
            <select
              value={speed}
              disabled={mode === "live"}
              onChange={(event) => setSpeed(Number(event.target.value))}
            >
              <option value={0.5}>0.5×</option>
              <option value={1}>1×</option>
              <option value={2}>2×</option>
              <option value={4}>4×</option>
            </select>
          </label>
        </div>
      </header>

      <div className="workspace">
        <div className="left-column">
          <form
            className="build-request"
            onSubmit={(event) => {
              event.preventDefault();
              setMode("live");
              if (agentSettings.configuration) {
                void liveRun.start(prompt, agentSettings.configuration);
              }
            }}
          >
            <label htmlFor="build-prompt">What should the team make?</label>
            <div className="build-input-row">
              <textarea
                id="build-prompt"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                maxLength={20_000}
                rows={2}
                placeholder="Describe the tool you have in mind…"
                required
              />
              <button
                type="submit"
                className="build-button"
                disabled={isLiveRunning || !prompt.trim() || !agentSettings.configuration}
              >
                {isLiveRunning
                  ? "The team is working…"
                  : agentSettings.loading && !agentSettings.configuration
                    ? "Loading agent settings…"
                    : "Build with configured LLM"}
              </button>
            </div>
            <div className="build-footnote" aria-live="polite">
              {liveRun.error && mode === "live"
                ? <span className="run-error">{liveRun.error}</span>
                : agentSettings.error
                  ? <span className="run-error">{agentSettings.error}</span>
                : mode === "live" && liveRun.model
                  ? <span>Using {liveRun.provider} · {liveRun.model}</span>
                  : <span>Real runs use the backend model. The demo below works without an API key.</span>}
              <button
                type="button"
                onClick={() => {
                  replay.replay();
                  setMode("demo");
                }}
              >
                Play the sample run
              </button>
            </div>
          </form>
          <section className="project-card">
            <div className="project-copy">
              <span className="section-kicker">TODAY’S BUILD</span>
              <h1>A CSV to JSON tool</h1>
              <p>With schema validation, just as requested.</p>
            </div>
            <div className="project-progress">
              <div className="progress-caption">
                <span>Team progress</span>
                <strong>{stage}</strong>
              </div>
              <ProgressBar progress={progress} />
            </div>
          </section>
          <OfficeView
            events={events}
            selectedAgent={selectedAgent}
            onAgentSelect={setSelectedAgent}
            names={names}
            colors={replay.agent}
          />
          {selectedAgent && (
            <section className="agent-card">
              <span
                className="agent-avatar"
                style={{ background: replay.agent[selectedAgent] }}
              >
                {names[selectedAgent][0]}
              </span>
              <div className="agent-detail">
                <div className="agent-name-line">
                  <strong>{names[selectedAgent]}</strong>
                  <span>{AGENT_LABELS[selectedAgent]}</span>
                </div>
                <p>{String(activeTask ?? tasks[selectedAgent])}</p>
              </div>
              {latestArtifact && (
                <span className="latest-artifact">
                  Latest: {String(latestArtifact.payload.artifact)}
                </span>
              )}
            </section>
          )}
        </div>
        <aside className="right-column">
          <UpdatesPanel events={events} />
          <TranscriptPanel events={events} />
          <SchedulePanel events={events} />
        </aside>
      </div>
      <AgentSettings
        open={settingsOpen}
        configuration={agentSettings.configuration}
        defaults={agentSettings.defaults}
        settingsError={agentSettings.error}
        onClose={() => setSettingsOpen(false)}
        onSave={agentSettings.save}
        onReset={() => {
          if (agentSettings.defaults) agentSettings.save(agentSettings.defaults);
        }}
      />
    </main>
  );
}

function ProgressBar({ progress }: { progress: number }) {
  return (
    <div
      className="progress-track"
      role="progressbar"
      aria-label="Team progress"
      aria-valuenow={progress}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="progress-fill" style={{ width: `${progress}%` }} />
    </div>
  );
}
