import pytest
from fastapi.testclient import TestClient

from talkboard.config import ConfigError, Settings, load_settings
from talkboard.server import create_app


def test_health_route_reports_ok(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path)), base_url="http://127.0.0.1:8765")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_settings_defaults_bind_to_localhost_only():
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.whisper_model == "mlx-community/whisper-large-v3-turbo"


def test_load_settings_reads_values_from_a_config_file(tmp_path):
    config_file = tmp_path / "talkboard.toml"
    config_file.write_text('port = 9000\nwhisper_model = "custom/model"\n')
    settings = load_settings(config_file)
    assert settings.port == 9000
    assert settings.whisper_model == "custom/model"
    assert settings.host == "127.0.0.1"


def test_load_settings_refuses_an_api_key_in_the_config_file(tmp_path):
    config_file = tmp_path / "talkboard.toml"
    config_file.write_text('anthropic_api_key = "sk-secret"\n')
    with pytest.raises(ConfigError, match="environment"):
        load_settings(config_file)


def test_load_settings_without_a_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "missing.toml") == Settings()
