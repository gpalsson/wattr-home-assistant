import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hacs_package_contract():
    manifest = json.loads((ROOT / "custom_components/wattr/manifest.json").read_text())
    assert manifest["domain"] == "wattr"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["requirements"] == []
    assert manifest["version"] == "0.1.0"
    assert (ROOT / "LICENSE").is_file()
    assert json.loads((ROOT / "hacs.json").read_text())["homeassistant"] == "2025.10.0"
    for forbidden in ["switch.py", "button.py", "number.py", "services.yaml"]:
        assert not (ROOT / "custom_components/wattr" / forbidden).exists()


def test_translations_cover_every_sensor():
    from custom_components.wattr.sensor import DESCRIPTIONS

    for lang in ["en", "da"]:
        data = json.loads(
            (ROOT / f"custom_components/wattr/translations/{lang}.json").read_text()
        )
        assert all(d.key in data["entity"]["sensor"] for d in DESCRIPTIONS)
        assert data["config"]["step"]["approve"]["description"].count("{url}") == 1
        assert set(data["entity"]["binary_sensor"]) == {"plugged_in", "charging"}
