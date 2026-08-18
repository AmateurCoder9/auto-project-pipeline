"""
test_model_selector.py - Unit tests for model selector module
"""

import responses

from model_selector import GEMINI_BASE, _rank, list_available_models


def test_model_ranking():
    assert _rank("gemini-2.0-flash-lite") < _rank("gemini-1.5-flash")
    assert _rank("gemini-1.5-flash") < _rank("gemini-1.5-pro")
    assert _rank("gemini-1.5-pro") < _rank("custom-unknown-model")

@responses.activate
def test_list_available_models_success():
    api_key = "test_key"
    url = f"{GEMINI_BASE}/models?key={api_key}"
    responses.add(
        responses.GET,
        url,
        json={
            "models": [
                {
                    "name": "models/gemini-1.5-flash",
                    "supportedGenerationMethods": ["generateContent"]
                },
                {
                    "name": "models/embedding-001",
                    "supportedGenerationMethods": ["embedContent"]
                }
            ]
        },
        status=200
    )

    models = list_available_models(api_key)
    assert len(models) == 1
    assert models[0]["name"] == "models/gemini-1.5-flash"
