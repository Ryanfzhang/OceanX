"""Desktop's file launcher must reuse native profiles without changing user state."""
import json
import os
import subprocess
import sys

import pytest

from oceanx.desktop_launcher import load_desktop_config, main, prepare_environment


def config_file(tmp_path, extra=""):
    path = tmp_path / "desktop.toml"
    path.write_text('''[model]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key_env = "DESKTOP_LAUNCH_KEY"
image_inputs = false
''' + extra)
    return path


def test_desktop_config_uses_native_models_and_keeps_old_settings(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"; legacy.mkdir()
    (legacy / "settings.json").write_text('{"model":"original"}')
    monkeypatch.setenv("OCEANMIND_CONFIG_DIR", str(legacy))
    monkeypatch.setenv("DESKTOP_LAUNCH_KEY", "desktop-secret")
    monkeypatch.setenv("VITE_CARTO_BASEMAPS_API_KEY", "stale-map")
    monkeypatch.setenv("ELECTRON_RUN_AS_NODE", "1")
    monkeypatch.setenv("OCEAN_DESKTOP_TEST_MODE", "1")
    path = config_file(tmp_path, '''
[desktop]
runtime_dir = "./generated"
[models.expert]
model = "expert-override"
[map]
carto_api_key = "public-map"
''')
    before = dict(os.environ)
    config = load_desktop_config(path)
    environment = prepare_environment(config, tmp_path)
    assert dict(os.environ) == before
    assert (legacy / "settings.json").read_text() == '{"model":"original"}'
    assert environment["OCEANMIND_CONFIG_DIR"] == str(tmp_path / "generated")
    assert environment["OCEAN_PYTHON"] == environment["OCEAN_SANDBOX_PYTHON"] == sys.executable
    assert environment["VITE_CARTO_BASEMAPS_API_KEY"] == "public-map"
    assert "ELECTRON_RUN_AS_NODE" not in environment and "OCEAN_DESKTOP_TEST_MODE" not in environment
    result = subprocess.run([sys.executable, "-c", '''
from oceanx.model_config import load_model_profile
c, e = (load_model_profile(role) for role in ('coordinator', 'expert'))
assert (c.model, e.model) == ('deepseek-flash', 'expert-override')
assert c.api_key == e.api_key == 'desktop-secret'
assert c.name == 'ocean-desktop-coordinator' and e.name == 'ocean-desktop-expert'
assert c.provider == e.provider == 'deepseek'
assert c.image_inputs is False
'''], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for name in ("settings.json", "credentials.json"):
        assert (tmp_path / "generated" / name).stat().st_mode & 0o777 == 0o600


def test_desktop_check_does_not_write_state_or_launch_app(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DESKTOP_LAUNCH_KEY", "private-desktop-key")
    path = config_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["desktop_launcher", "--config", str(path), "--check"])
    monkeypatch.setattr(os, "execvpe", lambda *_: pytest.fail("--check must not launch anything"))
    main()
    output = capsys.readouterr().out
    assert json.loads(output)["models"]["coordinator"]["model"] == "deepseek-flash"
    assert "private-desktop-key" not in output
    assert not (tmp_path / ".oceanx").exists()


@pytest.mark.parametrize("extra", [
    '[server]\nport=8765',
    '[desktop]\nmode="unknown"',
    '[desktop]\nruntime_dir=7',
    '[desktop]\nsandbox_python="./missing"',
    '[map]\ncarto_api_key=42',
])
def test_desktop_config_rejects_wrong_fields(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("DESKTOP_LAUNCH_KEY", "private-key")
    with pytest.raises(ValueError):
        load_desktop_config(config_file(tmp_path, extra))


def test_desktop_launcher_will_not_overwrite_existing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_LAUNCH_KEY", "private-key")
    monkeypatch.setenv("OCEANMIND_CONFIG_DIR", str(tmp_path / "legacy"))
    with pytest.raises(ValueError, match="separate"):
        load_desktop_config(config_file(tmp_path, '[desktop]\nruntime_dir="./legacy"'))


def test_desktop_syntax_errors_do_not_quote_keys(tmp_path):
    path = tmp_path / "desktop.toml"; path.write_text('[model]\napi_key="private-key" oops')
    with pytest.raises(ValueError) as error:
        load_desktop_config(path)
    assert "private-key" not in str(error.value)


def test_normal_launcher_delegates_to_original_npm_start(tmp_path, monkeypatch):
    import oceanx.desktop_launcher as launcher

    repo = tmp_path / "checkout"
    desktop = repo / "frontend/ocean-desktop"; (desktop / "node_modules").mkdir(parents=True)
    module = repo / "src/oceanx/desktop_launcher.py"
    module.parent.mkdir(parents=True); module.touch()
    monkeypatch.setattr(launcher, "__file__", str(module))
    monkeypatch.setenv("DESKTOP_LAUNCH_KEY", "private-key")
    path = config_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["desktop_launcher", "--config", str(path)])
    called = []
    monkeypatch.setattr(os, "execvpe", lambda command, args, env: called.append((command, args, env)))
    monkeypatch.chdir(tmp_path)
    main()
    assert called[0][:2] == ("npm", ["npm", "start"])
    assert called[0][2]["OCEANMIND_CONFIG_DIR"] == str(tmp_path / ".oceanx/desktop-launch")
    assert os.getcwd() == str(desktop)
