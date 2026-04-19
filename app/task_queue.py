"""
In-memory task queue for the autonomous agent pipeline.

Tasks submitted via Telegram commands are queued here and processed
sequentially by a background worker to avoid concurrent browser conflicts.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: str
    prompt: str
    notify: Optional[Callable[[str], Awaitable[None]]] = field(default=None, repr=False)


class TaskQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.get_event_loop().create_task(self._worker())
        logger.info("[task_queue] Worker started")

    def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
        logger.info("[task_queue] Worker stopped")

    async def submit(self, task_id: str, prompt: str, notify=None) -> None:
        task = Task(id=task_id, prompt=prompt, notify=notify)
        await self._queue.put(task)
        logger.info("[task_queue] Queued task %s: %s", task_id, prompt[:60])

    async def _worker(self) -> None:
        from app.agent_runner import run
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            logger.info("[task_queue] Processing task %s", task.id)
            try:
                result = await run(task.prompt, notify=task.notify)
                logger.info("[task_queue] Task %s done: success=%s", task.id, result.success)
            except Exception as exc:
                logger.exception("[task_queue] Task %s crashed: %s", task.id, exc)
                if task.notify:
                    try:
                        await task.notify(f"💥 Task crashed: {exc}")
                    except Exception:
                        pass
            finally:
                self._queue.task_done()


# Module-level singleton
queue = TaskQueue()
