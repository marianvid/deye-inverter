from datetime import time

import pytest

from deye_inverter.application.auth import PasswordError, PasswordService
from deye_inverter.application.scheduler import GuardedJob, JobScheduler
from deye_inverter.domain.settings import PlannerSettings


def test_guarded_job_logs_failures(world) -> None:
    def boom() -> None:
        raise RuntimeError("nope")

    GuardedJob("readings", boom, world.services.journal, world.clock)()
    entry = world.services.journal.recent("error", 1)[0]
    assert entry["job"] == "readings" and entry["message"] == "nope"


def test_scheduler_registers_jobs(world) -> None:
    scheduler = JobScheduler("Europe/Bucharest", world.services.journal, world.clock)
    scheduler.add_interval("readings", lambda: None, 5)
    calls = []
    scheduler.schedule_planner(PlannerSettings(), calls.append)
    scheduler.schedule_planner(PlannerSettings(), calls.append)
    scheduler.start()
    try:
        assert scheduler.next_check() is not None
        names = [run["job"] for run in scheduler.next_runs()]
        expected = len(JobScheduler.planner_times(PlannerSettings())) + 1
        assert "readings" in names and len(names) == expected
        assert {"planner-10:00", "planner-15:45", "planner-21:00", "planner-05:45"} <= set(names)
    finally:
        scheduler.shutdown()
    assert JobScheduler.planner_times(PlannerSettings())[-1] == time(23, 45)


def test_password_service(world) -> None:
    passwords: PasswordService = world.services.passwords
    assert not passwords.is_set() and not passwords.verify("anything")
    with pytest.raises(PasswordError):
        passwords.set("short")
    passwords.set("correct horse")
    assert passwords.is_set()
    assert passwords.verify("correct horse") and not passwords.verify("wrong horse")
    assert passwords.session_secret() == passwords.session_secret()
