"""One benchmark model for Coordinator, Experts and offline meta/labels; do not save settings."""
import asyncio
from pathlib import Path

from benchmark_config import load_config


def install_oceanx_models(config=None):
    from oceanx import model_config
    config = config or load_config()
    endpoint = config.endpoint(config.oceanx_api)
    slot = 'benchmark-env'
    original_key = model_config._stored_api_key

    def profile(settings, *, role='coordinator'):
        return slot, {'provider': config.oceanx_api, 'last_model': config.model,
                      'base_url': endpoint.url, 'credential_slot': slot}

    def key(*, provider, slot):
        if slot == 'benchmark-env':
            return endpoint.api_key
        return original_key(provider=provider, slot=slot)

    model_config._profile_payload = profile
    model_config._stored_api_key = key
    model_config._load_settings_payload = lambda: {
        'max_tokens': config.max_tokens, 'role_profiles': {'meta': slot}}
    return {**config.public(), 'roles': ['coordinator', 'expert', 'meta'],
            'api_profile': 'benchmarking/.env', 'scope': 'benchmark_process_only'}


async def run_oceanx_gateway(state_directory):
    """Use the production gateway, but bootstrap models in its actual server child.

    Only this dedicated benchmark gateway's launcher is adapted. Do not patch
    global asyncio or change the desktop entrypoint. Keys stay in the .env file,
    not in child arguments, environment additions or saved metadata.
    """
    from oceanx.research import launcher

    config = load_config()
    config.endpoint(config.oceanx_api)  # fail before launching on missing credentials
    entrypoint = Path(__file__).with_name('benchmark_agent_server.py').resolve()

    class BenchmarkLauncher:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def create_subprocess_exec(self, executable, *args, **kwargs):
            if args[:2] != ('-m', 'oceanx.research.server'):
                raise RuntimeError('OceanX Agent Server launch changed; update benchmark bootstrap')
            kwargs['env'] = {**kwargs['env'], 'OCEAN_BENCH_CONFIG': str(config.source)}
            return await asyncio.create_subprocess_exec(
                executable, str(entrypoint), *args[2:], **kwargs)

    original = launcher.asyncio
    launcher.asyncio = BenchmarkLauncher()
    try:
        return await launcher.run_desktop_gateway(state_directory)
    finally:
        launcher.asyncio = original
