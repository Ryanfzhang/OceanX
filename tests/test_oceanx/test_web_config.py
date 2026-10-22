"""Web API configuration reaches native role loaders without touching Desktop."""
import json
import os
import subprocess
import sys

import pytest
from starlette.testclient import TestClient

from oceanx.web.config import load_web_config, load_web_model_config
from oceanx.web.server import WebSettings, create_app
from tests.test_oceanx.test_web_entry import StubBackend


def write_config(tmp_path, extra=""):
    path = tmp_path / "web.toml"
    path.write_text('[model]\nprovider="deepseek"\nmodel="deepseek-flash"\n'
                    'base_url="https://api.deepseek.com"\napi_key_env="WEB_TEST_KEY"\n' + extra)
    return path


def test_web_config_uses_native_loaders_and_preserves_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_TEST_KEY", "web-private-key")
    desktop = tmp_path / "desktop"; desktop.mkdir()
    (desktop / "settings.json").write_text('{"model":"desktop-original"}')
    monkeypatch.setenv("OCEANMIND_CONFIG_DIR", str(desktop))
    config = load_web_model_config(write_config(tmp_path, '\n[models.expert]\nmodel="expert-override"\n'))
    root = config.materialize(tmp_path / "state/model-config")
    assert root != desktop
    assert os.environ["OCEANMIND_CONFIG_DIR"] == str(desktop)
    assert json.loads((desktop / "settings.json").read_text()) == {"model": "desktop-original"}
    for file in (root / "settings.json", root / "credentials.json"):
        assert file.stat().st_mode & 0o777 == 0o600
    # Both real native role loaders must use exactly the web-specific credentials,
    # even if the process also has a conflicting provider environment variable.
    result = subprocess.run([sys.executable, "-c", """
from oceanx.model_config import load_model_profile
c, e = [load_model_profile(role) for role in ('coordinator', 'expert')]
assert (c.model, e.model) == ('deepseek-flash', 'expert-override')
assert c.api_key == e.api_key == 'web-private-key'
assert c.provider == e.provider == 'deepseek'
assert c.base_url == e.base_url == 'https://api.deepseek.com'
"""], env={**os.environ, "OCEANMIND_CONFIG_DIR": str(root), "DEEPSEEK_API_KEY": "wrong-key"},
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_browser_status_never_contains_credentials_or_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_TEST_KEY", "web-private-key")
    config = load_web_model_config(write_config(tmp_path))
    frontend = tmp_path / "frontend"; frontend.mkdir()
    (frontend / "index.html").write_text("web")
    app = create_app(WebSettings(tmp_path / "workspace", frontend, model_config=config,
                                 carto_api_key="public-map-key"), backend_factory=StubBackend)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/config")
    assert response.json()["provider"]["coordinator"]["model"] == "deepseek-flash"
    assert response.json()["provider"]["expert"]["model"] == "deepseek-flash"
    assert response.json()["provider"]["configured"] is True
    assert response.json()["map"] == {"cartoKey": "public-map-key"}
    for secret in ("web-private-key", "WEB_TEST_KEY", "api.deepseek.com", str(tmp_path)):
        assert secret not in response.text
        assert secret not in repr(config)


@pytest.mark.parametrize("text", [
    '[model]\napi_key="secret"\nmodel="x"\nprovider="typo"',
    '[model]\napi_key="secret"\nmodel="x"\nprovider="deepseek"\nmax_tokens=true',
    '[model]\napi_key="secret"\nmodel="x"\nprovider="deepseek"\nimage_inputs="false"',
    '[model]\napi_key="secret"\nmodel="x"\nprovider="deepseek"\nbase_url="https://u:secret@example.test"',
    '[model]\napi_key="secret"\napi_key_env="WEB_TEST_KEY"\nmodel="x"\nprovider="deepseek"',
    '[model]\napi_key_env="MISSING_WEB_KEY"\nmodel="x"\nprovider="deepseek"',
    '[model]\napi_key="secret"\nmodel="x"\nprovider="deepseek"\napi_ky="secret"',
    '[models.typo]\napi_key="secret"',
    '[model]\napi_key="secret" oops',
])
def test_config_fails_closed_and_does_not_quote_secrets(tmp_path, text):
    path = tmp_path / "web.toml"; path.write_text(text)
    with pytest.raises(ValueError) as error:
        load_web_model_config(path)
    assert "secret" not in str(error.value)


def test_inline_key_can_override_shared_environment_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_TEST_KEY", "shared-key")
    config = load_web_model_config(write_config(tmp_path, '\n[models.expert]\napi_key="expert-key"\n'))
    assert config.roles["coordinator"]["api_key"] == "shared-key"
    assert config.roles["expert"]["api_key"] == "expert-key"


def test_one_config_controls_server_models_map_cleanup_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_TEST_KEY", "web-private-key")
    (tmp_path / "sources").mkdir()
    frontend = tmp_path / "frontend"; frontend.mkdir()
    (frontend / "index.html").write_text("web")
    path = write_config(tmp_path, '''
[server]
workspace = "./project"
frontend = "./frontend"
source_roots = ["./sources"]
port = 8768
log_dir = "./logs"
[cleanup]
cache_hours = 12
archived_cache_hours = 2
sweep_minutes = 15
[map]
carto_api_key = "public-map-key"
''')
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_web_config(path)
    assert config.workspace == tmp_path / "project"
    assert config.source_roots == (tmp_path / "sources",)
    assert config.log_dir == tmp_path / "logs"
    assert config.port == 8768
    assert (config.cache_hours, config.archived_cache_hours, config.sweep_seconds) == (12, 2, 900)
    assert config.carto_api_key == "public-map-key"
    assert config.model_config.roles["expert"]["model"] == "deepseek-flash"
    from oceanx.web.__main__ import main
    calls = []
    monkeypatch.setattr("oceanx.web.__main__.uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs)))
    monkeypatch.setattr(sys, "argv", ["oceanx.web", "--config", str(path)])
    main()
    app, options = calls[0]
    settings = app.state.backend.settings
    assert settings.workspace == config.workspace
    assert settings.log_dir == config.log_dir
    assert settings.carto_api_key == config.carto_api_key
    assert settings.model_config.roles == config.model_config.roles
    assert options["host"] == "127.0.0.1" and options["port"] == config.port
    assert options["log_config"]["handlers"]["web_file"]["filename"] == str(tmp_path / "logs/web-console.log")


@pytest.mark.parametrize("section", [
    '[server]\nworkspace="./project"\nport=0',
    '[server]\nworkspace="./project"\nsource_roots="/srv"',
    '[server]\nworkspace="./project"\nsource_roots=["./missing"]',
    '[server]\nworkspace="./project"\nsandbox_python="./missing-python"',
    '[server]\nworkspace="./project"\nsource_root=[]',
    '[server]\nworkspace="./project"\n[cleanup]\ncache_hours=nan',
    '[server]\nworkspace="./project"\n[cleanup]\nsweep_minutes=0',
    '[server]\nworkspace="./project"\n[map]\ncarto_api_key=42',
])
def test_unified_config_rejects_invalid_server_settings(tmp_path, monkeypatch, section):
    monkeypatch.setenv("WEB_TEST_KEY", "web-private-key")
    with pytest.raises(ValueError):
        load_web_config(write_config(tmp_path, section))
