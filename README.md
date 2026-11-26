# DevOffice

DevOffice is a PyQt6 desktop app for watching a multi-agent software team work. It calls LangGraph directly in a worker thread, uses Gemini for structured agent outputs or deterministic mock responses, and does not require a local HTTP server or WebSocket connection.

## Proposed structure

```text
backend/
  desktop/             PyQt6 office, dialogs, graph worker, and artifact export
  desktop_app.py       Native desktop entry point
  events/              Typed events, SQLite persistence, and replay
  graph/               LangGraph workflow and SQLite checkpoint runner
  agents/prompts/      Per-agent system prompts and output schemas
  tools/               Room booking and agent tools
  sandbox/             Isolated code execution
  tests/
projects/              Generated source folders, one unique folder per build run
runs/                  SQLite database and per-run events, LLM calls, workspace, and artifacts
docker-compose.yml
.env.example
README.md
```

## Event persistence

The event envelope is `{ id, run_id, ts, type, agent, room?, payload }`, where `id` is a UUID string, `ts` is a timezone-aware ISO 8601 timestamp, and `payload` is a JSON object. `agent` may be null for system events; `room` is optional.

The allowed `type` values are:

```text
agent_status | agent_move | room_booked | room_released
meeting_started | meeting_message | meeting_ended | artifact_created
review_verdict | test_result | security_finding | loop_iteration
milestone_update | error | run_complete
```

Events are validated with Pydantic and appended to SQLite plus `runs/<run_id>/events.jsonl`. The desktop app receives graph events directly through Qt signals and can replay saved runs from the history selector.

Install dependencies from the repository root:

```powershell
python -m pip install -r backend/requirements.txt
```

Set `DEV_OFFICE_RUNS_DIR` to change the directory for `events.sqlite3` and per-run logs. The backend loads the root `.env` file when present.

Run the test suite:

```powershell
python -m unittest discover -s backend/tests -v
```

## Step 2: meeting-room bookings

`RoomBookingService` stores bookings in `runs/rooms.sqlite3`. It provides `book_room`, `release_room`, and `list_rooms`; bookings are serialized across competing requests, room and attendee overlaps are rejected, and released bookings remain visible in the schedule. The three room IDs are `whiteboard_room`, `war_room`, and `focus_room`.

The legacy web integration exposes `GET /api/rooms`, `POST /api/rooms/{room_id}/bookings`, and `DELETE /api/rooms/bookings/{booking_id}?released_by=<organizer>`. The desktop app uses `RoomBookingService` directly. A booking accepts `organizer`, `attendees`, `topic`, `duration_minutes` (1-480), and optional timezone-aware `starts_at` (defaults to now).

The same unittest command above covers event streaming and persistence, booking conflicts, schedule persistence, and booking API behavior.

## Step 3: multi-agent graph

The LangGraph StateGraph includes Maya, Arjun, Dev, Sana, Tara, Doc, and Ojas. Gemini structured responses and mock responses are validated with the same Pydantic schemas. Invalid structured outputs are retried up to two times; design reviews and code fixes have bounded loops. Tester, code security, and code critic run as parallel branches. `GraphRunner` uses `SqliteSaver` with `run_id` as the checkpoint `thread_id`, so an interrupted run can resume after reopening the runner.

Run the CSV-to-JSON mock scenario:

```powershell
python -m backend.graph.demo
```

The demo CLI remains deliberately mock-only and does not execute generated code. Per-role prompts are in `backend/agents/prompts/`; the Gemini runtime is in `backend/agents/runtime.py`.

## Step 4: PyQt6 desktop office

The native application includes an animated top-down office, a safe non-executing build-canvas wireframe, a live tech-stack and plan-of-action dashboard, meeting transcripts, an updates feed, artifact browser, room schedule and booking controls, run history, spec approval, an LLM console, and ZIP export. The graph runs in a `QThread`; typed events and LLM request/response records are persisted locally and delivered to the UI with Qt signals. Generated code is packaged but never executed by the desktop preview.

Start the application on Windows by double-clicking `start.bat`, or run it manually:

```powershell
python -m pip install -r backend/requirements.txt
python -m backend.desktop_app
```

The desktop app stores agent names/prompts, animation speed, and the selected Gemini model in `QSettings`, so these preferences apply to later launches and future runs. Open **Settings** for the nested **Agents**, **Animation**, and **LLM Model** tabs; agent prompt placeholders include `{{agent_name}}` and `{{context}}`. Build outputs are saved in a unique folder under `E:\AI dev team\projects` as well as a per-run workspace under `runs/`; the ZIP deliverable and final state remain under that run's `artifacts/`. Open **LLM Console** to inspect each live request, structured response, validation retry, and error. The console records are replayable from `runs/<run_id>/llm_calls.jsonl`.

## Gemini setup

1. Copy `.env.example` to `.env` (the Windows `start.bat` creates it on first launch).
2. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey) and add it as `GEMINI_API_KEY` in `.env`. Keep this file local; it is ignored by Git and is never exposed in the desktop UI.
3. Keep `DEV_OFFICE_LLM_PROVIDER=gemini` and start/restart the desktop app. The default model is `gemini-4-hydrogen`; you can also choose or type a model ID in **Settings → LLM Model** for future runs.
4. Launch the desktop app and enter a build request. The API key remains in the local process environment and is never placed in the UI configuration.
5. Gemini HTTP 429 responses are retried with bounded backoff, and parallel agent calls are serialized. If `RESOURCE_EXHAUSTED` persists, wait for the quota window to reset or check that model's API quota and billing in Google AI Studio; DevOffice will not silently switch models.

For no-key demos, set `DEV_OFFICE_LLM_PROVIDER=mock`. The former FastAPI/WebSocket and React/Vite sources remain available as legacy integrations, but the PyQt6 desktop application does not start or depend on them. The workflow generates structured artifacts and review results; generated code is not executed.
