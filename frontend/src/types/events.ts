export type EventType =
  | "agent_status"
  | "agent_move"
  | "room_booked"
  | "room_released"
  | "meeting_started"
  | "meeting_message"
  | "meeting_ended"
  | "artifact_created"
  | "review_verdict"
  | "test_result"
  | "security_finding"
  | "loop_iteration"
  | "milestone_update"
  | "error"
  | "run_complete";

export interface EventEnvelope {
  id: string;
  run_id: string;
  ts: string;
  type: EventType;
  agent: string | null;
  room?: string | null;
  payload: Record<string, unknown>;
}
