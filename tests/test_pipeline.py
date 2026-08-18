"""
test_pipeline.py - Unit tests for pipeline orchestrator & state machine
"""

import pytest

from common import PipelineError
from pipeline import load_log, save_log, validate_config


def test_config_validation_missing_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(PipelineError, match="Missing GEMINI_API_KEY"):
        validate_config()

def test_load_and_save_log(tmp_path, monkeypatch):
    log_path = tmp_path / "test_projects_log.json"
    monkeypatch.setattr("pipeline.LOG_FILE", str(log_path))

    initial_log = load_log()
    assert initial_log == []

    test_data = [
        {
            "title": "Test App",
            "description": "A test app",
            "status": "logged",
            "timestamp": "2026-08-18T12:00:00"
        }
    ]
    save_log(test_data)
    
    loaded_data = load_log()
    assert len(loaded_data) == 1
    assert loaded_data[0]["title"] == "Test App"
    assert loaded_data[0]["status"] == "logged"
