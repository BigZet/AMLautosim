import json,httpx,subprocess
from pathlib import Path
s=json.loads(Path(".local-run/predeploy-2026-09-20/settings.json").read_text())
with httpx.Client(base_url="http://127.0.0.1:18000/api/v1") as c:
 r=c.post("/auth/login",json={"email":s["BOOTSTRAP_ADMIN_EMAIL"],"password":s["BOOTSTRAP_ADMIN_PASSWORD"],"audience":"admin"});r.raise_for_status();h={"X-Session-ID":r.json()["session_id"]}
 game=c.get("/admin/rounds/current",headers=h).json()
 print("Container model",game["game_config"]["risk_model"]["model_version"])
 config={k:v for k,v in game["game_config"].items() if k not in {"config_version","card_snapshots","risk_model"}}
 config["objectives"]["target_outflow"]="100000.00"
 r=c.put(f"/admin/rounds/{game['id']}",headers=h,json={"game_config":config,"expected_config_revision":game["config_revision"]})
 print("Custom objective save",r.status_code,r.json().get("code"))
 print("API ready",httpx.get("http://127.0.0.1:18000/health/ready").status_code)
 print("UI live",httpx.get("http://127.0.0.1:18080/health/live").status_code)
print(subprocess.check_output(["docker","exec","aml-predeploy-20260920-api-1","python","-c","import os,pathlib; print('uid',os.getuid()); print('new_package_in_image',pathlib.Path('/app/resources/catboost_models/aml-game-organizer-settings-v1').exists()); print('app_writable',os.access('/app',os.W_OK))"],text=True))
