import numpy as np
import pandas as pd
from scripts.aml_game_curriculum import candidate
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import extract_panel_features, assess_panel
from src.aml_workshop_simulator.services import aml_game_window_model as window


def test_window_targets_equal_original_chain_policy():
    features = [extract_panel_features(candidate(s)[1]) for s in range(120)]
    targets = np.array([assess_panel(f)['target_probability'] for f in features])
    projected = window.views(pd.DataFrame(features))
    assert np.allclose(window.interpretation_targets(projected).reshape(3,120).mean(axis=0),targets,atol=1e-12,rtol=0)


def test_inference_averages_model_probabilities_without_using_targets(monkeypatch):
    def forbidden(*args):
        raise AssertionError('Runtime must not compute policy labels')
    monkeypatch.setattr(window,'interpretation_targets',forbidden)
    class Model:
        def predict_proba(self,frame):
            assert list(frame) == window.FEATURES
            assert len(frame) == 3
            return np.array([[.8,.2],[.5,.5],[.2,.8]])
    features = extract_panel_features(candidate(0)[1])
    assert window.score_features(Model(),{'calibration':{'method':'none'}},features) == .5