import sys,json,time,statistics,tempfile,shutil
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from src.aml_workshop_simulator.services.game_classifier import get_game_classifier,GameClassifier
m=get_game_classifier();base=json.loads(Path("tests/fixtures/retired_limits_baseline.json").read_text())
for r in base["rows"]:
    assert m.extract(r["steps"])==r["features"]
    assert m.predict(r["steps"],m.context,require_pin=False,explain=False)==r["probability"]
rows=json.loads(Path(".local-run/classifier-release/scoring-ui-scenarios.json").read_text())
latencies=[];probs=[];max_residual=0
for r in rows:
    start=time.perf_counter();e=m.predict(r["steps"],m.context,require_pin=False)
    latencies.append(time.perf_counter()-start);probs.append(e["aml_probability"])
    for w in e["windows"]:
        residual=abs(w["base_margin"]+sum(f["contribution"] for f in w["shap_values"])-w["raw_margin"])
        max_residual=max(max_residual,residual);assert residual<1e-7
with tempfile.TemporaryDirectory(prefix="aml-package-audit-") as t:
    dest=Path(t)/"copy";shutil.copytree(m.package,dest)
    with (dest/"features.json").open("a") as f:f.write(" ")
    try:GameClassifier(dest)
    except ValueError:pass
    else:raise AssertionError("Corrupted artifact accepted")
print(json.dumps(dict(baseline_equal=25,scored=15,probability_min=min(probs),probability_max=max(probs),shap_max_residual=max_residual,seconds_total=sum(latencies),median_ms=statistics.median(latencies)*1000,max_ms=max(latencies)*1000,corruption_rejected=True),indent=2))
