from tests.fakes import winter_table


def test_send_verifies_and_logs(world) -> None:
    table = winter_table(soc=40)
    outcome = world.services.time_of_use.send(table, "manual")
    assert outcome.status == "executed" and outcome.verified
    assert world.services.state.current_table() == table
    entry = world.services.journal.recent("command", 1)[0]
    assert entry["reason"] == "manual" and entry["slots"][0]["soc"] == 40
    assert world.services.time_of_use.writes_today() == 1


def test_rejected_mismatch_and_failure(world) -> None:
    world.gateway.accept = False
    assert world.services.time_of_use.send(winter_table(soc=40), "manual").status == "failed"
    world.gateway.accept = True
    world.gateway.ignore_writes = True
    assert world.services.time_of_use.send(winter_table(soc=40), "manual").status == "mismatch"
    world.gateway.fail = True
    outcome = world.services.time_of_use.send(winter_table(soc=40), "manual")
    assert outcome.status == "failed" and "cloud down" in outcome.message
