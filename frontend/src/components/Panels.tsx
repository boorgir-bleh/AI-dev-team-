import type { EventEnvelope } from "../types/events";
import { AGENT_COLORS, type AgentRole } from "../types/agents";

function shortTime(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function UpdatesPanel({ events }: { events: EventEnvelope[] }) {
  const updates = events.filter((event) => event.type === "milestone_update").slice(-5).reverse();
  return (
    <section className="panel updates-panel">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">FROM MAYA</span>
          <h2>Along the way</h2>
        </div>
        {updates.length > 0 && <span className="count">{updates.length}</span>}
      </div>
      <div className="panel-scroll">
        {updates.map((event) => (
          <article className="update-card" key={event.id}>
            <div className="update-meta">
              <span>{String(event.payload.stage)}</span>
              <time>{shortTime(event.ts)}</time>
            </div>
            <p>{String(event.payload.message)}</p>
            {Array.isArray(event.payload.risks) && event.payload.risks.length > 0 && (
              <span className="risk-note">Worth keeping an eye on</span>
            )}
          </article>
        ))}
        {updates.length === 0 && <p className="empty">Maya will leave a note when the team reaches its first milestone.</p>}
      </div>
    </section>
  );
}

export function TranscriptPanel({ events }: { events: EventEnvelope[] }) {
  const messages = events.filter((event) =>
    event.type === "meeting_started" ||
    event.type === "meeting_message" ||
    event.type === "meeting_ended"
  ).slice(-8);
  return (
    <section className="panel transcript-panel">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">AT THE TABLE</span>
          <h2>What they’re saying</h2>
        </div>
        {messages.length > 0 && <span className="count">{messages.length}</span>}
      </div>
      <div className="panel-scroll">
        {messages.map((event) => (
          <div className={`transcript-row ${event.type}`} key={event.id}>
            {event.type === "meeting_message" ? (
              <>
                <span
                  className="speaker-dot"
                  style={{
                    background: AGENT_COLORS[event.payload.agent_role as AgentRole] ?? "#8b907f",
                  }}
                />
                <div>
                  <div className="speaker-line">
                    <strong>{event.agent}</strong>
                    <time>{shortTime(event.ts)}</time>
                  </div>
                  <span>{String(event.payload.text)}</span>
                </div>
              </>
            ) : (
              <>
                <span className="transcript-mark">{event.type === "meeting_started" ? "↗" : "✓"}</span>
                <span>
                  {event.type === "meeting_started"
                    ? `${String(event.payload.topic ?? "A meeting")} started`
                    : "Meeting wrapped up"}
                </span>
              </>
            )}
          </div>
        ))}
        {messages.length === 0 && <p className="empty">Pull up a chair. The first meeting will show up here.</p>}
      </div>
    </section>
  );
}

export function SchedulePanel({ events }: { events: EventEnvelope[] }) {
  const bookings = events.filter((event) => event.type === "room_booked" || event.type === "room_released");
  return (
    <section className="panel schedule-panel">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">ROOMS</span>
          <h2>Who’s meeting where</h2>
        </div>
      </div>
      <div className="room-list">
        {["Whiteboard Room", "War Room", "Focus Room"].map((room) => {
          const booking = [...bookings].reverse().find((event) => event.room === room);
          const isBooked = booking?.type === "room_booked";
          return (
            <div className="room-row" key={room}>
              <span className={`room-state ${isBooked ? "busy" : ""}`} />
              <div>
                <strong>{room}</strong>
                <span>
                  {isBooked
                    ? `${String(booking.payload.topic ?? "Meeting")} · with ${String(booking.agent)}`
                    : "Free for a chat"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
