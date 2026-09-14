import json
from collections import Counter

import pytest

from scripts.aml_dataset.mass_release import review_sample, review_contract, generate_mass


def test_short_sample_is_disjoint_reproducible_and_four_per_category():
    rows = [dict(id=str(i), target_risk_score=i / 2,
                 baseline=dict(risk_score=100 - i / 2)) for i in range(200)]
    sample = review_sample(rows, (4, 4, 4))
    assert len({r["record"]["id"] for r in sample}) == 12
    assert Counter(r["reason"] for r in sample) == {
        "risk_range": 4, "boundary": 4, "baseline_disagreement": 4}
    assert sample == review_sample(rows, (4, 4, 4))
    assert len(review_sample(rows)) == 120


def test_short_policy_removes_blind_gate_but_keeps_pilot_approval(tmp_path, monkeypatch):
    from scripts.aml_dataset import mass_release
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    assert review_contract(pilot)["blind"] is True
    (pilot / "review-policy.json").write_text(json.dumps(dict(
        version="human-12-no-blind-v1", user_evidence="Explicit user request")))
    assert review_contract(pilot)["blind"] is False
    seen = []
    monkeypatch.setattr(mass_release, "check_joint_review",
                        lambda path, require_blind=False: seen.append(require_blind))
    monkeypatch.setattr(mass_release, "read_json", lambda path: {})
    # Keep the real review-contract lookup for the call, despite mocked manifest reads.
    monkeypatch.setattr(mass_release, "review_contract", lambda path: {"blind": False})
    def pending(*args):
        raise ValueError("Joint pilot review is pending")
    monkeypatch.setattr(mass_release, "verify_pilot_review", pending)
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="pending"):
        generate_mass(tmp_path, output, "release", pilot_dir=pilot)
    assert seen == [False]
    assert not output.exists()


def test_unknown_policy_rejected(tmp_path):
    (tmp_path / "review-policy.json").write_text('{"version":"anything"}')
    with pytest.raises(ValueError, match="policy"):
        review_contract(tmp_path)
