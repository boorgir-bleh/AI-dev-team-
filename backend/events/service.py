import asyncio

from backend.events.schema import EventEnvelope
from backend.events.store import EventStore, StoredEvent


class EventBroker:
    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[StoredEvent | None]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str) -> asyncio.Queue[StoredEvent | None]:
        queue: asyncio.Queue[StoredEvent | None] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue[StoredEvent | None]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(run_id)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if not subscribers:
                del self._subscribers[run_id]

    async def publish(self, stored_event: StoredEvent) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(stored_event.event.run_id, set())
            for queue in tuple(subscribers):
                try:
                    queue.put_nowait(stored_event)
                except asyncio.QueueFull:
                    while not queue.empty():
                        queue.get_nowait()
                    queue.put_nowait(None)
                    subscribers.discard(queue)


class EventService:
    def __init__(self, store: EventStore, broker: EventBroker | None = None) -> None:
        self.store = store
        self.broker = broker or EventBroker()

    async def publish(self, event: EventEnvelope) -> EventEnvelope:
        stored_event = self.store.append(event)
        await self.broker.publish(stored_event)
        return event
