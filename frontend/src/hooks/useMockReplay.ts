import { useEffect, useRef, useState } from "react";
import {
  AGENT_COLORS,
  AGENT_ROLES,
  DEFAULT_AGENT_NAMES,
  type AgentRole,
} from "../types/agents";
import type { EventEnvelope } from "../types/events";

const runId = "mock-csv-demo";

type MockEvent = Omit<EventEnvelope, "id" | "run_id" | "ts">;

const mockEvents: MockEvent[] = [
  { type: "agent_status", agent: "Maya", payload: { status: "working", activity: "turning prompt into a spec" } },
  { type: "milestone_update", agent: "Maya", payload: { stage: "1 of 8", message: "Maya prepared the specification. Arjun is starting the design.", status: "in_progress", risks: [] } },
  { type: "room_booked", agent: "Maya", room: "Whiteboard Room", payload: { topic: "Kickoff", attendees: ["Maya", "Arjun", "Dev", "Sana", "Tara", "Doc", "Ojas"] } },
  { type: "meeting_started", agent: "Maya", room: "Whiteboard Room", payload: { topic: "Kickoff", goal: "Align on the CSV-to-JSON tool" } },
  { type: "meeting_message", agent: "Maya", room: "Whiteboard Room", payload: { text: "Acceptance criteria are clear: validate each row, report failures, and write valid JSON." } },
  { type: "meeting_message", agent: "Arjun", room: "Whiteboard Room", payload: { text: "I’ll keep it as a small CLI with a parser, validator, and JSON writer." } },
  { type: "meeting_ended", agent: "Maya", room: "Whiteboard Room", payload: { decisions: ["Use a standard-library implementation"], action_items: ["Arjun to complete the design"], blockers: [] } },
  { type: "room_released", agent: "Maya", room: "Whiteboard Room", payload: { topic: "Kickoff" } },
  { type: "artifact_created", agent: "Arjun", payload: { artifact: "design", title: "Technical design" } },
  { type: "room_booked", agent: "Arjun", room: "War Room", payload: { topic: "Design Review", attendees: ["Arjun", "Sana", "Ojas", "Maya"] } },
  { type: "meeting_started", agent: "Arjun", room: "War Room", payload: { topic: "Design Review", goal: "Approve components and threat model" } },
  { type: "meeting_message", agent: "Sana", room: "War Room", payload: { text: "We should reject malformed schemas before writing any output." } },
  { type: "meeting_message", agent: "Ojas", room: "War Room", payload: { text: "Define the invalid-row behavior explicitly; otherwise maintainers will guess." } },
  { type: "review_verdict", agent: "Ojas", payload: { phase: "design", verdict: "APPROVE", comments: [] } },
  { type: "security_finding", agent: "Sana", payload: { phase: "design", gate: "PASS", finding: null } },
  { type: "meeting_ended", agent: "Arjun", room: "War Room", payload: { decisions: ["Approve the design"], action_items: ["Dev to begin implementation"], blockers: [] } },
  { type: "room_released", agent: "Arjun", room: "War Room", payload: { topic: "Design Review" } },
  { type: "milestone_update", agent: "Maya", payload: { stage: "3 of 8", message: "Design review passed. Dev is starting implementation.", status: "in_progress", risks: [] } },
  { type: "agent_status", agent: "Dev", payload: { status: "working", activity: "implementing the approved design" } },
  { type: "artifact_created", agent: "Dev", payload: { artifact: "code", files: ["src/main.py", "src/converter.py", "tests/test_converter.py"], summary: "Implementation artifacts ready for review." } },
  { type: "milestone_update", agent: "Maya", payload: { stage: "4 of 8", message: "Dev prepared the implementation artifacts. Tara, Sana, and Ojas are reviewing them.", status: "in_progress", risks: [] } },
  { type: "room_booked", agent: "Dev", room: "Focus Room", payload: { topic: "Code Review", attendees: ["Dev", "Ojas", "Sana", "Tara"] } },
  { type: "meeting_started", agent: "Dev", room: "Focus Room", payload: { topic: "Code Review", goal: "Review code, tests, and security" } },
  { type: "test_result", agent: "Tara", payload: { passed: 2, failed: 0, failing_cases: [], repro_steps: [] } },
  { type: "security_finding", agent: "Sana", payload: { phase: "code", gate: "PASS", finding: null } },
  { type: "review_verdict", agent: "Ojas", payload: { phase: "code", verdict: "APPROVE", comments: [] } },
  { type: "meeting_message", agent: "Ojas", room: "Focus Room", payload: { text: "The implementation is scoped and the acceptance path is covered." } },
  { type: "meeting_ended", agent: "Dev", room: "Focus Room", payload: { decisions: ["Approve for documentation and delivery"], action_items: ["Doc to prepare usage notes"], blockers: [] } },
  { type: "room_released", agent: "Dev", room: "Focus Room", payload: { topic: "Code Review" } },
  { type: "artifact_created", agent: "Doc", payload: { artifact: "documentation", files: ["README.md"], summary: "Usage documentation prepared." } },
  { type: "milestone_update", agent: "Maya", payload: { stage: "7 of 8", message: "Doc prepared the usage notes. Maya is checking final acceptance.", status: "in_progress", risks: [] } },
  { type: "milestone_update", agent: "Maya", payload: { stage: "8 of 8", message: "The run passed every configured mock gate. The final tool is ready.", status: "completed", risks: [] } },
  { type: "run_complete", agent: "Maya", payload: { accepted: true, status: "completed", known_issues: [], summary: "The run passed its configured mock acceptance gates." } },
];

function roleForDefaultName(name: string): AgentRole | undefined {
  return AGENT_ROLES.find((role) => DEFAULT_AGENT_NAMES[role] === name);
}

function remapNames(value: unknown, names: Record<AgentRole, string>): unknown {
  if (typeof value === "string") {
    const lookup = new Map(AGENT_ROLES.map((role) => [DEFAULT_AGENT_NAMES[role], names[role]]));
    const pattern = new RegExp(`\\b(${AGENT_ROLES.map((role) => DEFAULT_AGENT_NAMES[role]).join("|")})\\b`, "g");
    return value.replace(pattern, (match) => lookup.get(match) ?? match);
  }
  if (Array.isArray(value)) return value.map((item) => remapNames(item, names));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, remapNames(item, names)]),
    );
  }
  return value;
}

export function useMockReplay(speed: number, configuredNames: Record<AgentRole, string>) {
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [playing, setPlaying] = useState(true);
  const [cursor, setCursor] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!playing || cursor >= mockEvents.length) return;
    timer.current = window.setTimeout(() => {
      const base = mockEvents[cursor];
      const role = base.agent ? roleForDefaultName(base.agent) : undefined;
      const payload = remapNames(base.payload, configuredNames) as Record<string, unknown>;
      if (role) payload.agent_role = role;
      const event: EventEnvelope = {
        ...base,
        agent: role ? configuredNames[role] : base.agent,
        payload,
        id: `mock-${cursor + 1}`,
        run_id: runId,
        ts: new Date(Date.now()).toISOString(),
      };
      setEvents((current) => [...current, event]);
      setCursor((current) => current + 1);
    }, 1150 / speed);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [configuredNames, cursor, playing, speed]);

  const replay = () => {
    setEvents([]);
    setCursor(0);
    setPlaying(true);
  };

  return {
    events,
    cursor,
    total: mockEvents.length,
    playing,
    setPlaying,
    replay,
    runId,
    agent: AGENT_COLORS,
  };
}
