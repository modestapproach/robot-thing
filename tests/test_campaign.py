import pytest

from orchestrator.campaign import Campaign, CampaignInterrupted
from shared.store import MemoryStore


def test_campaign_resumes_without_repeating_moves(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = str(tmp_path / "state.pkl")
    s1 = MemoryStore(path)
    c1 = Campaign(s1, log=lambda m: None)
    with pytest.raises(CampaignInterrupted):
        c1.run(stop_after="disturbance")
    moves_before = s1.count("hardware_commands", {"status": "acknowledged"})
    keys_before = {d["idempotency_key"] for d in s1.find("hardware_commands", {})}

    s2 = MemoryStore(path)  # new process
    c2 = Campaign(s2, campaign_id=c1.c.id, log=lambda m: None)
    assert c2.lab.bumped  # physical world state restored from checkpoint
    out = c2.run()
    keys_after = [d["idempotency_key"] for d in s2.find("hardware_commands", {})]
    assert len(keys_after) == len(set(keys_after))  # no key executed twice
    assert keys_before <= set(keys_after)
    assert s2.count("hardware_commands", {"status": "acknowledged"}) > moves_before
    assert out["recovered"]["version"] >= 2
    assert all(t["success"] for t in out["recovered"]["trials"])


def test_dashboard_pause_is_honoured_between_stages(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = MemoryStore()
    c = Campaign(s, log=lambda m: None)
    orig = c.stage_baseline

    def baseline_then_pause():
        out = orig()
        s.update("experiment_campaigns", c.c.id, {"pause_requested": True})  # what the dashboard does
        return out

    c.stage_baseline = baseline_then_pause
    with pytest.raises(CampaignInterrupted, match="paused by operator"):
        c.run()
    doc = s.get("experiment_campaigns", c.c.id)
    assert doc["status"] == "paused" and "recalibrate" not in doc["checkpoint"]["completed"]


def test_dashboard_requested_campaign_is_adopted(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = MemoryStore()
    s.insert("experiment_campaigns", {"_id": "camp_req_1", "objective": "from dashboard", "status": "requested", "baseline_version_id": None,
                                      "scenario_set_id": "targets_v1", "checkpoint": {"completed": [], "outputs": {}, "lab": {"bumped": False}}})
    out = Campaign(s, campaign_id="camp_req_1", log=lambda m: None).run()
    assert s.get("experiment_campaigns", "camp_req_1")["status"] == "completed" and "report" in out
