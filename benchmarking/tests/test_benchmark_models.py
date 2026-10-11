import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from benchmark_config import Config, Endpoint, claude_environment, load_config
from benchmark_models import install_oceanx_models, run_oceanx_gateway

from oceanx import model_config
from oceanx.agent import load_model_profile as imported_loader


def config():
    return Config('test-model', 'openai', {
        'openai': Endpoint('https://openai.example/v1', 'private-test-key'),
        'anthropic': Endpoint('https://anthropic.example', 'other-private-key')})


def test_env_overrides_all_roles_and_stored_credentials_without_saving(monkeypatch):
    for name in ['_profile_payload', '_stored_api_key', '_load_settings_payload']:
        monkeypatch.setattr(model_config, name, getattr(model_config, name))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'wrong-old-key')
    c = config()
    policy = install_oceanx_models(c)
    for role in policy['roles']:
        p = imported_loader(role)
        assert (p.model, p.provider, p.base_url, p.api_key) == (
            'test-model', 'openai', 'https://openai.example/v1', 'private-test-key')
    assert 'private' not in json.dumps(policy)
    assert 'private' not in repr(c)
    meta = imported_loader('meta')
    assert (meta.model, meta.provider, meta.api_key) == ('test-model', 'openai', 'private-test-key')
    assert model_config._load_settings_payload()['role_profiles']['meta'] == 'benchmark-env'


def test_claude_environment_replaces_old_routing(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://wrong.example')
    monkeypatch.setenv('CLAUDE_CODE_USE_BEDROCK', '1')
    monkeypatch.setenv('ANTHROPIC_DEFAULT_HAIKU_MODEL', 'wrong-model')
    env = claude_environment(config())
    assert env['ANTHROPIC_BASE_URL'] == 'https://anthropic.example'
    assert env['ANTHROPIC_AUTH_TOKEN'] == 'other-private-key'
    assert env['ANTHROPIC_DEFAULT_HAIKU_MODEL'] == 'test-model'
    assert 'CLAUDE_CODE_USE_BEDROCK' not in env


def test_config_errors_do_not_expose_keys(tmp_path):
    p = tmp_path/'.env'
    p.write_text('DEEPSEEK_API_KEY="secret-do-not-print\n')
    with pytest.raises(ValueError) as exc:
        load_config(p)
    assert 'secret-do-not-print' not in str(exc.value)
    p.write_text('BENCH_MODEL=test\nBENCH_OPENAI_BASE_URL=https://example/v1\nDEEPSEEK_API_KEY=key\n')
    c = load_config(p)
    assert c.endpoint('openai').api_key == 'key'
    assert c.endpoint('anthropic').api_key == 'key'


def test_single_key_defaults_to_flash_for_both_protocols(tmp_path, monkeypatch):
    p = tmp_path / '.env'
    p.write_text('DEEPSEEK_API_KEY=test-shared-key\n')
    c = load_config(p)
    assert c.model == 'deepseek-flash' and c.oceanx_api == 'openai'
    assert c.endpoint('openai').url == 'https://api.deepseek.com'
    assert c.endpoint('anthropic').url == 'https://api.deepseek.com/anthropic'
    assert c.endpoint('openai').api_key == c.endpoint('anthropic').api_key == 'test-shared-key'
    for name in ['_profile_payload', '_stored_api_key', '_load_settings_payload']:
        monkeypatch.setattr(model_config, name, getattr(model_config, name))
    policy = install_oceanx_models(c)
    assert [imported_loader(role).model for role in policy['roles']] == ['deepseek-flash'] * 3
    env = claude_environment(c)
    assert env['ANTHROPIC_MODEL'] == env['CLAUDE_CODE_SUBAGENT_MODEL'] == 'deepseek-flash'
    assert env['ANTHROPIC_API_KEY'] == 'test-shared-key'
    assert 'test-shared-key' not in json.dumps(c.public())
    assert 'test-shared-key' not in repr(c)


def test_separate_meta_model_or_unknown_credentials_are_rejected(tmp_path):
    p = tmp_path / '.env'
    p.write_text('DEEPSEEK_API_KEY=private-shared\nBENCH_META_MODEL=another-model\n')
    with pytest.raises(ValueError, match='unsupported'):
        load_config(p)
    p.write_text('DEEPSEEK_API_KEY=private-shared\nOPENAI_API_KEY=private-other\n')
    with pytest.raises(ValueError, match='unsupported') as exc:
        load_config(p)
    assert 'private-' not in str(exc.value)


def test_env_never_inherits_credentials_or_interpolates_shell(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'old-shell-secret')
    p = tmp_path / '.env'
    p.write_text('BENCH_MODEL=deepseek-flash\n')
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        load_config(p).endpoint('openai')
    p.write_text('DEEPSEEK_API_KEY="literal-${DEEPSEEK_API_KEY}#quoted"\n')
    assert load_config(p).endpoint('openai').api_key == 'literal-${DEEPSEEK_API_KEY}#quoted'
    assert os.environ['DEEPSEEK_API_KEY'] == 'old-shell-secret'


@pytest.mark.parametrize('body', ['BENCH_MAX_TOKENS=0', 'BENCH_MAX_TOKENS=not-an-integer',
                                 'BENCH_MODEL=', 'BENCH_OCEANX_API=invalid',
                                 'BENCH_MODEL=one\nBENCH_MODEL=two'])
def test_bad_env_fails_before_model_calls(tmp_path, body):
    p = tmp_path / '.env'
    p.write_text(body + '\nDEEPSEEK_API_KEY=test-key\n')
    with pytest.raises(ValueError):
        load_config(p)


def test_missing_env_message_and_default_path(tmp_path):
    from benchmark_config import DEFAULT_CONFIG, ROOT
    assert DEFAULT_CONFIG == ROOT / 'benchmarking' / '.env'
    with pytest.raises(ValueError, match='benchmarking/.env.example'):
        load_config(tmp_path / 'missing.env')


def test_gateway_adapts_only_its_launcher_and_restores_it(tmp_path, monkeypatch):
    import asyncio

    from oceanx.research import launcher

    env_file = tmp_path / '.env'
    env_file.write_text('DEEPSEEK_API_KEY=only-in-file\n')
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(env_file))
    original = launcher.asyncio
    observed = []

    async def spawn(*args, **kwargs):
        observed.append((args, kwargs))
        return 'child'

    async def gateway(state):
        assert launcher.asyncio is not asyncio
        assert launcher.asyncio.sleep is asyncio.sleep
        return await launcher.asyncio.create_subprocess_exec(
            sys.executable, '-m', 'oceanx.research.server', '--state', str(state), '--port', '1234',
            env={'OCEAN_SERVER_TOKEN': 'launcher-token'}, stdin='stdin', stdout='log', stderr='log')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(launcher, 'run_desktop_gateway', gateway)
    assert asyncio.run(run_oceanx_gateway(tmp_path / 'state')) == 'child'
    assert launcher.asyncio is original
    args, kwargs = observed[0]
    assert args == (sys.executable,
                    str(Path(__file__).resolve().parents[1] / 'server/benchmark_agent_server.py'),
                    '--state', str(tmp_path / 'state'), '--port', '1234')
    assert kwargs == {'env': {'OCEAN_SERVER_TOKEN': 'launcher-token',
                              'OCEAN_BENCH_CONFIG': str(env_file)},
                      'stdin': 'stdin', 'stdout': 'log', 'stderr': 'log'}
    assert 'only-in-file' not in repr(observed)

    async def changed_gateway(state):
        await launcher.asyncio.create_subprocess_exec(sys.executable, '-m', 'other.server', env={})

    monkeypatch.setattr(launcher, 'run_desktop_gateway', changed_gateway)
    with pytest.raises(RuntimeError, match='launch changed'):
        asyncio.run(run_oceanx_gateway(tmp_path / 'state'))
    assert launcher.asyncio is original
    assert len(observed) == 1


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_backend_loads_flash_in_actual_server_child_despite_stored_pro(tmp_path, protocol):
    """Real runner -> production gateway -> real child, with only server I/O stubbed.

    No LLM requests: the stub reads real profiles and builds the real API adapters
    at the production run_server boundary, then exits instead of serving HTTP.
    """
    root = Path(__file__).resolve().parents[2]
    server = root / 'benchmarking/server'
    desktop = tmp_path / 'desktop'
    desktop.mkdir()
    settings = {'provider': 'openai', 'model': 'deepseek-v4-pro',
                'base_url': 'https://api.deepseek.com', 'max_tokens': 65536}
    (desktop / 'settings.json').write_text(json.dumps(settings))
    (desktop / 'credentials.json').write_text(json.dumps({'openai': {'api_key': 'stored-pro-key'}}))
    env_file = tmp_path / '.env'
    env_file.write_text('DEEPSEEK_API_KEY=benchmark-flash-key\nBENCH_MODEL=deepseek-flash\n'
                        f'BENCH_OCEANX_API={protocol}\n')
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    # Only replace the HTTP server's final entrypoint, not OceanX's launcher,
    # model loader, adapter or server main. It captures what the agents will use.
    stub = tmp_path / 'stub' / 'langgraph_api'
    stub.mkdir(parents=True)
    (stub / '__init__.py').write_text('')
    (stub / 'cli.py').write_text('''
import json
import os
from pathlib import Path

def run_server(**kwargs):
    from oceanx.model_config import load_model_profile, create_chat_model
    profiles = {role: load_model_profile(role) for role in ('coordinator', 'expert', 'meta')}
    models = {role: create_chat_model(p) for role, p in profiles.items()}
    record = {'pid': os.getpid(), 'graphs': kwargs['graphs'],
              'profiles': {role: {'model': p.model, 'provider': p.provider,
                                 'base_url': p.base_url, 'max_tokens': p.max_tokens,
                                 'correct_key': p.api_key == 'benchmark-flash-key',
                                 'request_model': (models[role].model_name if p.provider == 'openai'
                                                   else models[role].model)}
                           for role, p in profiles.items()}}
    Path('observed-models.json').write_text(json.dumps(record))
''')
    env = {**os.environ, 'OCEANMIND_CONFIG_DIR': str(desktop),
           'OCEAN_BENCH_CONFIG': str(env_file),
           'PYTHONPATH': os.pathsep.join([str(stub.parent), str(server), str(root / 'src'),
                                        os.environ.get('PYTHONPATH', '')]),
           'NO_PROXY': '127.0.0.1,localhost'}
    # A fresh ordinary process still sees Pro; simply inheriting the benchmark
    # .env path does not reconfigure it (and must not change desktop behavior).
    ordinary = subprocess.run([sys.executable, '-c',
                               ('from oceanx.model_config import load_model_profile; '
                                'print(load_model_profile().model)')],
                              env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False)
    assert ordinary.returncode == 0, ordinary.stderr
    assert ordinary.stdout.strip() == 'deepseek-v4-pro'
    process = subprocess.Popen([sys.executable, str(server / 'run_oceanx.py'), '--backend', str(attempt)],
                               env=env, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    try:
        stdout, stderr = process.communicate(timeout=45)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    # The fake HTTP server exits intentionally, so the production readiness
    # check reports failure. Its captured model configuration is the assertion.
    assert process.returncode != 0
    assert 'Agent Server failed to start' in stderr
    observed = json.loads((attempt / 'state/observed-models.json').read_text())
    policy = json.loads((attempt / 'model_protocol.json').read_text())
    assert observed['pid'] != process.pid
    assert policy['pid'] == observed['pid'] and policy['scope'] == 'agent_server_process'
    assert observed['graphs'] == {'coordinator': 'oceanx.research.graphs:coordinator'}
    endpoint = 'https://api.deepseek.com' + ('/anthropic' if protocol == 'anthropic' else '')
    for role, profile in observed['profiles'].items():
        assert profile == {'model': 'deepseek-flash', 'provider': protocol,
                           'base_url': endpoint, 'max_tokens': 32768,
                           'correct_key': True, 'request_model': 'deepseek-flash'}
        assert policy['profiles'][role] == {k: v for k, v in profile.items()
                                           if k not in {'correct_key', 'request_model'}}
    assert 'benchmark-flash-key' not in json.dumps(policy) + stdout + stderr
    assert json.loads((desktop / 'settings.json').read_text()) == settings


def test_gateway_missing_config_does_not_fall_back_to_desktop(tmp_path, monkeypatch):
    import asyncio

    from oceanx.research import launcher

    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(tmp_path / 'missing.env'))
    original = launcher.asyncio
    with pytest.raises(ValueError, match='Missing'):
        asyncio.run(run_oceanx_gateway(tmp_path / 'state'))
    assert launcher.asyncio is original
    assert not (tmp_path / 'state').exists()
    assert not (tmp_path / 'model_protocol.json').exists()
