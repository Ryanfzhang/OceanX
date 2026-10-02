import json
import os

import pytest
from benchmark_config import Config, Endpoint, load_config, claude_environment
from benchmark_models import install_oceanx_models
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
