import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.aml_workshop_simulator.schemas.leaderboard import ResultOut


@pytest.mark.parametrize("version", [3, 4])
def test_saved_api_response_discriminates_without_changing_values(version):
    payload = json.loads(Path(f"tests/fixtures/scoring-api/result-v{version}.json")
                         .read_text(encoding="utf-8"))
    result = ResultOut.model_validate(payload)
    serialized = result.model_dump(mode="json")
    assert serialized == payload
    assert result.explanation.schema_version == version
    if version == 4:
        assert result.explanation.aml_probability == 0.09999
        assert result.explanation.category == "low"
        assert result.scores.risk_score == "10.00"
    payload["explanation"]["schema_version"] = 4 if version == 3 else 3
    with pytest.raises(ValidationError):
        ResultOut.model_validate(payload)
