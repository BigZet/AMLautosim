import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from src.aml_workshop_simulator.services.game_classifier import GameClassifier,get_pinned_game_classifier
for name in ["aml-game-v1","aml-game-relaxed-v1","aml-game-attributes-v1","aml-game-attribute-context-v1"]:
 m=GameClassifier(Path("resources/catboost_models")/name)
 selected=get_pinned_game_classifier({**m.context,"risk_model":m.identity})
 selected.check_config({**m.context,"risk_model":m.identity},require_pin=True)
 print(name,"real pin accepted",selected.package.name)
