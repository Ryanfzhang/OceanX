"""One explicit benchmark configuration; never inherit credentials from shell settings."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv.parser import parse_stream

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'benchmarking' / '.env'
DEFAULT_MODEL = 'deepseek-flash'
DEFAULT_ENDPOINTS = {'openai': 'https://api.deepseek.com',
                     'anthropic': 'https://api.deepseek.com/anthropic'}
RUN_DEFAULTS = {
    'BENCH_DATA_ROOT': '', 'BENCH_OUTPUT_ROOT': '', 'BENCH_EXPERIMENT': 'methods-public-r1',
    'BENCH_SUITE': 'test', 'BENCH_EVOLUTION_SET': '', 'BENCH_TASKS': 'available',
    'BENCH_TIMEOUT_SECONDS': '10800', 'BENCH_LITERATURE_MODE': 'search_only', 'BENCH_RESUME': 'false',
    'BENCH_OCEANX_ARM': 'OceanX', 'BENCH_OCEANX_LIBRARY': '', 'BENCH_OCEANX_MAX_PARALLEL_EXPERTS': '3',
    'BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS': '1', 'BENCH_OCEANX_EXPERT_CALL_LIMIT': '40',
    'BENCH_CLAUDE_EXECUTABLE': 'claude', 'BENCH_CLAUDE_ARM': 'Claude', 'BENCH_CLAUDE_ALLOW_TOOLS': '',
    'BENCH_FINCH_ROOT': '', 'BENCH_FINCH_PYTHON': '', 'BENCH_FINCH_KERNEL_PYTHON': '',
    'BENCH_FINCH_COMMIT': 'aea66fdf2dd2be827727de50a73cae60dff59972',
    'BENCH_FINCH_BWRAP': 'bwrap', 'BENCH_FINCH_ARM': 'Finch', 'BENCH_FINCH_MAX_STEPS': '60',
    'BENCH_FINCH_TEMPERATURE': '1', 'BENCH_FINCH_EXECUTION_TIMEOUT': '1200',
    'BENCH_FINCH_MEMORY_MB': '8192', 'BENCH_FINCH_CPUS': '2',
}


@dataclass(frozen=True)
class Endpoint:
    url: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class Config:
    model: str
    oceanx_api: str
    endpoints: dict[str, Endpoint] = field(repr=False)
    max_tokens: int = 32768
    run: dict[str, str] = field(default_factory=dict, repr=False)
    source: Path | None = field(default=None, repr=False)

    def endpoint(self, protocol):
        e = self.endpoints.get(protocol)
        if not e or not e.url or not e.api_key or e.api_key.startswith('REPLACE_'):
            raise ValueError('benchmarking/.env: fill DEEPSEEK_API_KEY')
        u = urlsplit(e.url)
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError(f'benchmarking/.env: invalid BENCH_{protocol.upper()}_BASE_URL')
        return e

    def public(self):
        return {'model': self.model, 'oceanx_api': self.oceanx_api, 'max_tokens': self.max_tokens,
                'endpoints': {k: {'url': v.url} for k, v in self.endpoints.items()}}


def load_config(path=None):
    path = Path(path or os.environ.get('OCEAN_BENCH_CONFIG', DEFAULT_CONFIG)).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'Missing {path}; copy benchmarking/.env.example to benchmarking/.env and fill it')
    # Parse this file only: no shell credential fallback, global load_dotenv or ${ENV} interpolation.
    raw = {}
    with path.open(encoding='utf-8') as stream:
        for binding in parse_stream(stream):
            if binding.error:
                raise ValueError(f'Invalid benchmark .env syntax at line {binding.original.line}')
            if binding.key:
                if binding.key in raw:
                    raise ValueError(f'Duplicate benchmark .env field at line {binding.original.line}')
                raw[binding.key] = binding.value or ''
    allowed = {'DEEPSEEK_API_KEY', 'BENCH_MODEL', 'BENCH_OCEANX_API', 'BENCH_MAX_TOKENS',
               'BENCH_OPENAI_BASE_URL', 'BENCH_ANTHROPIC_BASE_URL'} | set(RUN_DEFAULTS)
    if set(raw) - allowed:
        raise ValueError('benchmark .env has unsupported fields; use the fields in benchmarking/.env.example')
    model = raw.get('BENCH_MODEL', DEFAULT_MODEL).strip()
    if not model or model.startswith('REPLACE_'):
        raise ValueError('benchmarking/.env: fill BENCH_MODEL (default deepseek-flash)')
    protocol = raw.get('BENCH_OCEANX_API', 'openai').strip()
    if protocol not in ('openai', 'anthropic'):
        raise ValueError('benchmarking/.env: BENCH_OCEANX_API must be openai or anthropic')
    try:
        tokens = int(raw.get('BENCH_MAX_TOKENS', '32768'))
    except ValueError:
        raise ValueError('benchmarking/.env: BENCH_MAX_TOKENS must be a positive integer') from None
    if tokens < 1:
        raise ValueError('benchmarking/.env: BENCH_MAX_TOKENS must be a positive integer')
    key = raw.get('DEEPSEEK_API_KEY', '').strip()
    endpoints = {name: Endpoint(raw.get(f'BENCH_{name.upper()}_BASE_URL', url).strip(), key)
                 for name, url in DEFAULT_ENDPOINTS.items()}
    return Config(model, protocol, endpoints, tokens,
                  {k: raw.get(k, v).strip() for k, v in RUN_DEFAULTS.items()}, path)


def load_runner_config(method, path=None):
    """Settings for one runner, which may have a file of its own.

    In order: the named file; `OCEAN_BENCH_CONFIG`; the runner's own `benchmarking/.env.<method>`
    (`.env.oceanx`, `.env.claude`, `.env.finch`) when that file exists; the shared `benchmarking/.env`.

    A runner reads its experiment, questions and resume flag once, but OceanX's server process and
    Finch's worker read the same file again at the start of every case for the model settings. With
    a file per method, three runners can run at the same time and nobody edits a file in use.
    """
    if path is None and not os.environ.get('OCEAN_BENCH_CONFIG'):
        own = DEFAULT_CONFIG.with_name(f'{DEFAULT_CONFIG.name}.{method.lower()}')
        if own.is_file():
            path = own
    resolved = Path(path or os.environ.get('OCEAN_BENCH_CONFIG') or DEFAULT_CONFIG).expanduser().resolve()
    # Said before the file is parsed, so an error about a setting names the file it was read from.
    print(f'{method} settings: {resolved}', flush=True)
    return load_config(resolved)


def configure_runtime():
    """The benchmark's active interpreter is also its scientific runtime."""
    import sys
    if sys.version_info < (3, 11):
        raise ValueError('Activate oceanx-bench with Python 3.11 or newer')
    os.environ['OCEAN_SANDBOX_PYTHON'] = sys.executable
    os.environ['OCEAN_BENCH_RENDER_PYTHON'] = sys.executable


def preflight(require_sandbox=False):
    from oceanx.sandbox.execution import current_python_runtime
    configure_runtime()
    current_python_runtime()
    if require_sandbox:
        import asyncio
        from oceanx.sandbox_self_check import run_kernel_self_check, run_sandbox_self_check
        report = asyncio.run(run_sandbox_self_check())
        if not report.get('passed'):
            raise ValueError('Benchmark sandbox check failed before model calls: ' + str(report))
        report = asyncio.run(run_kernel_self_check())
        if not report.get('passed'):
            raise ValueError('Benchmark kernel check failed before model calls: ' + str(report))


def claude_environment(config):
    endpoint = config.endpoint('anthropic')
    env = dict(os.environ)
    # Remove old routing, aliases and cloud-provider modes from the inherited shell.
    for name in list(env):
        if name.startswith(('ANTHROPIC_', 'CLAUDE_CODE_USE_', 'CLAUDE_CODE_SUBAGENT_MODEL')):
            env.pop(name)
    env.update(ANTHROPIC_BASE_URL=endpoint.url, ANTHROPIC_AUTH_TOKEN=endpoint.api_key,
               ANTHROPIC_API_KEY=endpoint.api_key, ANTHROPIC_MODEL=config.model,
               ANTHROPIC_DEFAULT_OPUS_MODEL=config.model,
               ANTHROPIC_DEFAULT_SONNET_MODEL=config.model,
               ANTHROPIC_DEFAULT_HAIKU_MODEL=config.model,
               CLAUDE_CODE_SUBAGENT_MODEL=config.model)
    env['DISABLE_AUTOUPDATER'] = '1'
    return env
