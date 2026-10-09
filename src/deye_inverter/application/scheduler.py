"""Background jobs: collection, settings refresh, forecast, planner checks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import time
from functools import partial
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from deye_inverter.domain.settings import PlannerSettings
from deye_inverter.ports import Clock, JournalRepository

LOG = logging.getLogger(__name__)
ERROR = "error"
PLANNER_JOB_PREFIX = "planner-"


class JobChain:
    """Composite: runs several jobs in order as one scheduled job."""

    def __init__(self, *jobs: Callable[[], Any]) -> None:
        self._jobs = jobs

    def __call__(self) -> None:
        for job in self._jobs:
            job()


class GuardedJob:
    """Decorator: a failing job is logged to the journal instead of crashing the scheduler."""

    def __init__(
        self, name: str, job: Callable[[], Any], journal: JournalRepository, clock: Clock
    ) -> None:
        self._name = name
        self._job = job
        self._journal = journal
        self._clock = clock

    def __call__(self) -> None:
        try:
            self._job()
        except Exception as error:
            LOG.warning("Job %s failed: %s", self._name, error)
            self._journal.add(
                ERROR,
                self._clock.now(),
                {"status": "failed", "job": self._name, "message": str(error)},
            )


class JobScheduler:
    def __init__(self, timezone: str, journal: JournalRepository, clock: Clock) -> None:
        self._scheduler = BackgroundScheduler(timezone=timezone)
        self._journal = journal
        self._clock = clock
        self._timezone = timezone

    def add_interval(self, name: str, job: Callable[[], Any], minutes: int) -> None:
        self._scheduler.add_job(
            self._guard(name, job),
            IntervalTrigger(minutes=minutes, timezone=self._timezone),
            id=name,
            name=name,
            replace_existing=True,
            next_run_time=self._clock.now(),
        )

    def schedule_planner(self, settings: PlannerSettings, job: Callable[[str], Any]) -> None:
        for existing in self._scheduler.get_jobs():
            if existing.id.startswith(PLANNER_JOB_PREFIX):
                existing.remove()
        for moment in self.planner_times(settings):
            label = moment.strftime("%H:%M")
            self._scheduler.add_job(
                self._guard(f"planner {label}", partial(job, f"check {label}")),
                CronTrigger(hour=moment.hour, minute=moment.minute, timezone=self._timezone),
                id=f"{PLANNER_JOB_PREFIX}{label}",
                name=f"planner {label}",
                replace_existing=True,
            )

    @staticmethod
    def planner_times(settings: PlannerSettings) -> list[time]:
        return list(settings.tuning.check_times())

    def next_runs(self) -> list[dict[str, str]]:
        jobs = sorted(self._scheduler.get_jobs(), key=lambda j: j.next_run_time or 0)
        return [
            {"job": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else ""}
            for j in jobs
        ]

    def next_check(self) -> str | None:
        """When the planner runs next (ISO time), or None before the scheduler starts."""
        times = [
            job.next_run_time
            for job in self._scheduler.get_jobs()
            if job.id.startswith(PLANNER_JOB_PREFIX) and job.next_run_time
        ]
        return min(times).isoformat() if times else None

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _guard(self, name: str, job: Callable[[], Any]) -> GuardedJob:
        return GuardedJob(name, job, self._journal, self._clock)
