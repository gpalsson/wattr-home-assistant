import copy
import time

import pytest


@pytest.fixture
def tokens():
    return {
        "access_token": "test-access",
        "refresh_token": "test-refresh",
        "account_id": "test-account",
        "expires_at": time.time() + 900,
    }


@pytest.fixture
def token_response():
    return {
        "access_token": "rotated-access",
        "refresh_token": "rotated-refresh",
        "account_id": "test-account",
        "token_type": "Bearer",
        "scope": "read",
        "expires_in": 900,
    }


@pytest.fixture
def snapshot():
    return copy.deepcopy(
        {
            "api_version": 1,
            "account_id": "test-account",
            "generated_at": "2026-10-13T10:00:00Z",
            "installations": [
                {
                    "id": "test-home",
                    "name": "Test home",
                    "has_inverter": True,
                    "has_solar": True,
                    "battery_soc_percent": 50.5,
                    "battery_power_kw": -0.8,
                    "house_power_kw": 0.8,
                    "grid_power_kw": 0.02,
                    "solar_power_kw": None,
                    "read_at": "2026-10-13T09:55:00Z",
                    "inverter_status": "Brug batteriet",
                    "today": {
                        "date": "2026-10-13",
                        "import_kwh": 0,
                        "import_cost_dkk": 0,
                        "savings_dkk": -1.2,
                    },
                    "plan": {
                        "built_at": "2026-10-13T09:00:00Z",
                        "intervals": [
                            {
                                "start": "2026-10-13T10:00:00Z",
                                "end": "2026-10-13T10:15:00Z",
                                "car_kwh": 1.5,
                            }
                        ],
                    },
                    "cars": [
                        {
                            "id": "test-car",
                            "name": "Car",
                            "soc_percent": 88.7,
                            "plugged_in": True,
                            "charging": False,
                        }
                    ],
                    "charger": {
                        "plugged_in": True,
                        "charging": False,
                        "power_kw": 0,
                        "plan_cost_dkk": 4.1,
                    },
                }
            ],
        }
    )


@pytest.fixture(autouse=True)
def aiohttp_test_response_compatibility(monkeypatch):
    """Adapt aioresponses to aiohttp's added stream_writer constructor argument.

    Only its test response factory is patched; real client/stream tests use aiohttp unchanged.
    """
    import inspect
    from types import SimpleNamespace

    import aioresponses.core
    from aiohttp import ClientResponse

    if "stream_writer" in inspect.signature(ClientResponse).parameters:

        def build(*args, **kwargs):
            return ClientResponse(
                *args, stream_writer=SimpleNamespace(output_size=0), **kwargs
            )

        monkeypatch.setattr(aioresponses.core, "ClientResponse", build)
