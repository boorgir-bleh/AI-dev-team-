import { motion } from "framer-motion";
import {
  AGENT_ROLES,
  type AgentRole,
} from "../types/agents";
import type { EventEnvelope } from "../types/events";

interface OfficeViewProps {
  events: EventEnvelope[];
  selectedAgent: AgentRole | null;
  onAgentSelect: (agent: AgentRole) => void;
  names: Record<AgentRole, string>;
  colors: Record<AgentRole, string>;
}

const desks: Record<AgentRole, { x: number; y: number }> = {
  orchestrator: { x: 120, y: 102 },
  architect: { x: 325, y: 102 },
  developer: { x: 530, y: 102 },
  cyber_security: { x: 735, y: 102 },
  tester: { x: 220, y: 207 },
  documentation: { x: 425, y: 207 },
  critic: { x: 630, y: 207 },
};

const rooms = [
  { name: "Whiteboard Room", x: 35, y: 330, w: 240, h: 126, accent: "#7c9a83" },
  { name: "War Room", x: 320, y: 330, w: 240, h: 126, accent: "#c27a5c" },
  { name: "Focus Room", x: 605, y: 330, w: 240, h: 126, accent: "#8d82a6" },
];

function roomSeats(room: (typeof rooms)[number], count: number) {
  return Array.from({ length: count }, (_, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(count, 1);
    return {
      x: room.x + room.w / 2 + Math.cos(angle) * 70,
      y: room.y + 82 + Math.sin(angle) * 34,
    };
  });
}

export default function OfficeView({
  events,
  selectedAgent,
  onAgentSelect,
  names,
  colors,
}: OfficeViewProps) {
  const lastMeetingEvent = [...events]
    .reverse()
    .find((event) => event.type === "meeting_started" || event.type === "meeting_ended");
  const isMeetingActive = lastMeetingEvent?.type === "meeting_started";
  const latestMeeting = isMeetingActive ? lastMeetingEvent : null;
  const latestBooking = latestMeeting
    ? [...events].reverse().find(
        (event) => event.type === "room_booked" && event.room === latestMeeting.room,
      )
    : null;
  const attendees = Array.isArray(latestBooking?.payload.attendees)
    ? latestBooking.payload.attendees.filter((name): name is string => typeof name === "string")
    : [];
  const activeRoom = latestMeeting?.room ?? null;
  const latestMessage = latestMeeting
    ? [...events].reverse().find(
        (event) => event.type === "meeting_message" && event.room === latestMeeting.room,
      )
    : null;
  const activeRoomData = rooms.find((room) => room.name === activeRoom);
  const seats = activeRoomData ? roomSeats(activeRoomData, attendees.length) : [];
  const today = new Intl.DateTimeFormat("en", {
    weekday: "long",
    month: "short",
    day: "numeric",
  }).format(new Date());

  return (
    <section className="office-shell">
      <div className="office-topbar">
        <div>
          <span className="office-eyebrow">THE FLOOR</span>
          <strong>{today} at DevOffice</strong>
        </div>
        <span className="floor-status">
          <i className="live-dot" />
          {isMeetingActive ? `In a meeting · ${activeRoom}` : "Everyone at their desks"}
        </span>
      </div>
      <svg className="office-map" viewBox="0 0 880 510" role="img" aria-label="Animated DevOffice floor plan">
        <defs>
          <pattern id="floor-grain" width="56" height="56" patternUnits="userSpaceOnUse">
            <path d="M0 55.5H56" fill="none" stroke="#e4ddd0" strokeWidth="1" />
            <circle cx="9" cy="12" r="1" fill="#e1d9cb" />
            <circle cx="39" cy="34" r=".8" fill="#e1d9cb" />
          </pattern>
          <filter id="soft-shadow" x="-30%" y="-30%" width="160%" height="170%">
            <feDropShadow dx="0" dy="3" stdDeviation="3" floodColor="#544a3e" floodOpacity=".13" />
          </filter>
        </defs>
        <rect width="880" height="510" rx="14" fill="#eee8dc" />
        <rect width="880" height="510" rx="14" fill="url(#floor-grain)" />

        <rect x="22" y="23" width="836" height="274" rx="18" fill="#f3eee4" stroke="#ddd5c7" />
        <text x="44" y="49" className="map-label">OPEN PLAN</text>
        <text x="834" y="49" textAnchor="end" className="map-note">7 desks · 1 team</text>
        <path d="M37 67H843" stroke="#e4ddd0" strokeWidth="1" />

        {AGENT_ROLES.map((role) => {
          const position = desks[role];
          return (
          <g key={role}>
            <g filter="url(#soft-shadow)">
              <rect x={position.x - 39} y={position.y - 24} width="78" height="60" rx="9" fill="#d6b99b" stroke="#b99b7c" />
              <rect x={position.x - 21} y={position.y - 14} width="42" height="26" rx="4" fill="#3c4842" />
              <rect x={position.x - 17} y={position.y - 10} width="34" height="18" rx="2" fill="#d5e0d1" />
              <path d={`M${position.x - 15} ${position.y + 22}h30`} stroke="#b18c6a" strokeWidth="3" strokeLinecap="round" />
              <circle cx={position.x + 29} cy={position.y - 12} r="5" fill="#fbf8f1" stroke="#b99b7c" />
            </g>
            <text x={position.x} y={position.y + 78} textAnchor="middle" className="desk-label">{names[role]}</text>
          </g>
          );
        })}

        <g className="plant" transform="translate(52 252)">
          <path d="M0 14h25l-3 20H3z" fill="#bd8568" />
          <path d="M12 14C4 4 2 -1 4 -8c8 2 11 8 9 16M14 14c2-13 8-20 15-22 2 9-3 17-13 23M12 14C11 1 14-7 21-12c5 7 3 16-6 26" fill="#7d987c" />
        </g>
        <g className="plant" transform="translate(803 252)">
          <path d="M0 14h25l-3 20H3z" fill="#bd8568" />
          <path d="M12 14C4 4 2 -1 4 -8c8 2 11 8 9 16M14 14c2-13 8-20 15-22 2 9-3 17-13 23M12 14C11 1 14-7 21-12c5 7 3 16-6 26" fill="#7d987c" />
        </g>

        <rect x="34" y="309" width="812" height="166" rx="18" fill="#e9e1d4" stroke="#d8cebd" />
        <text x="53" y="326" className="map-label">MEETING ROOMS</text>
        {rooms.map((room) => (
          <g key={room.name}>
            <rect
              x={room.x}
              y={room.y}
              width={room.w}
              height={room.h}
              rx="12"
              fill={activeRoom === room.name ? "#fcfaf5" : "#f5f0e7"}
              stroke={activeRoom === room.name ? room.accent : "#d6cbbb"}
              strokeWidth={activeRoom === room.name ? 2 : 1}
            />
            <rect x={room.x + 12} y={room.y + 12} width="5" height="20" rx="2.5" fill={room.accent} />
            <text x={room.x + 27} y={room.y + 27} className="room-name">{room.name}</text>
            <text x={room.x + room.w - 14} y={room.y + 27} textAnchor="end" className="room-availability">
              {activeRoom === room.name ? "IN USE" : "AVAILABLE"}
            </text>
            <rect x={room.x + 38} y={room.y + 52} width={room.w - 76} height="48" rx="21" fill="#d5c3a9" />
            <rect x={room.x + 56} y={room.y + 64} width={room.w - 112} height="24" rx="11" fill="#8d9b83" opacity=".8" />
            {activeRoom === room.name && latestMeeting && (
              <text x={room.x + room.w / 2} y={room.y + room.h - 11} textAnchor="middle" className="meeting-topic">
                {String(latestMeeting.payload.topic ?? "Team meeting")}
              </text>
            )}
          </g>
        ))}

        <rect x="36" y="483" width="810" height="15" rx="7.5" fill="#dfd5c5" />
        <circle cx="64" cy="490.5" r="4" fill="#c17d61" />
        <text x="77" y="494" className="kitchen-text">COFFEE CORNER</text>
        <path d="M178 488v6m4-6v6" stroke="#a99b88" strokeWidth="2" strokeLinecap="round" />
        <text x="198" y="494" className="map-note">Fresh pot, if you get there before Dev.</text>

        {AGENT_ROLES.map((role) => {
          const position = desks[role];
          const home = { x: position.x, y: position.y + 40 };
          const attendeeIndex = attendees.indexOf(names[role]);
          const target = attendeeIndex >= 0 && activeRoomData
            ? seats[attendeeIndex]
            : home;
          const statusEvent = [...events].reverse().find(
            (event) => event.payload.agent_role === role && event.type === "agent_status",
          );
          const isWorking = statusEvent?.payload.status === "working";
          return (
            <motion.g
              key={role}
              animate={{ x: target.x - home.x, y: target.y - home.y }}
              transition={{ duration: 1.15, ease: [0.22, 1, 0.36, 1] }}
              onClick={() => onAgentSelect(role)}
              className={`office-person ${selectedAgent === role ? "selected-person" : ""}`}
              role="button"
              aria-label={`View ${names[role]}`}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onAgentSelect(role);
              }}
            >
              <ellipse cx={home.x} cy={home.y + 24} rx="13" ry="5" fill="#615b50" opacity=".16" />
              <path d={`M${home.x - 10} ${home.y + 13}q10-8 20 0l4 14h-28z`} fill={colors[role]} />
              <circle cx={home.x} cy={home.y + 3} r="10" fill="#f1c8a9" stroke="#a7795b" strokeWidth=".8" />
              <path d={`M${home.x - 9} ${home.y + 2}q1-12 10-10 8 0 9 10-4-4-8-5-4 5-11 5`} fill="#51443d" />
              <circle cx={home.x - 3} cy={home.y + 4} r=".8" fill="#473e39" />
              <circle cx={home.x + 3} cy={home.y + 4} r=".8" fill="#473e39" />
              {isWorking && attendeeIndex < 0 && (
                <g className="typing-indicator">
                  <circle cx={home.x - 5} cy={home.y - 13} r="2" fill="#6f8e71" />
                  <circle cx={home.x} cy={home.y - 16} r="2" fill="#6f8e71" />
                  <circle cx={home.x + 5} cy={home.y - 13} r="2" fill="#6f8e71" />
                </g>
              )}
              {selectedAgent === role && <circle cx={home.x} cy={home.y + 3} r="14" className="person-selection" />}
            </motion.g>
          );
        })}

        {latestMessage && (
          <motion.g initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} key={latestMessage.id}>
            <rect x="250" y="287" width="380" height="30" rx="15" fill="#fffdf8" stroke="#d8cebd" />
            <text x="440" y="306" textAnchor="middle" className="speech-text">
              “{String(latestMessage.payload.text).slice(0, 68)}”
            </text>
          </motion.g>
        )}
      </svg>
    </section>
  );
}
