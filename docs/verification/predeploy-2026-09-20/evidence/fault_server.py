import uvicorn
from src.aml_workshop_simulator.services import scoring_service
original=scoring_service._evaluate
calls=0
def fail_once(*args,**kwargs):
    global calls
    calls+=1
    if calls==2:raise RuntimeError("Audit controlled failure after first scenario")
    return original(*args,**kwargs)
scoring_service._evaluate=fail_once
uvicorn.run("src.aml_workshop_simulator.api.main:app",host="0.0.0.0",port=8000)
