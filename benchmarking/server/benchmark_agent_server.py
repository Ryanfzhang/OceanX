"""Benchmark-only entrypoint: configure models before loading production graphs."""
import argparse
import json
import os
from pathlib import Path

from benchmark_models import install_oceanx_models
from benchmark_skills import install_benchmark_skills


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get('OCEAN_SERVER_TOKEN'):
        raise RuntimeError('A local-launch authentication token is required')

    # This process executes the agents. A gateway's monkeypatch cannot cross
    # the Python subprocess boundary, even though its environment is inherited.
    policy = install_oceanx_models()
    # Benchmark-only skills, kept outside the OceanX package (benchmark_skills.py).
    skills = install_benchmark_skills()
    from oceanx.model_config import load_model_profile
    profiles = {role: load_model_profile(role) for role in policy['roles']}
    record = {**policy, 'scope': 'agent_server_process', 'pid': os.getpid(), 'benchmark_skills': skills,
              'profiles': {role: {'model': profile.model, 'provider': profile.provider,
                                  'base_url': profile.base_url, 'max_tokens': profile.max_tokens}
                           for role, profile in profiles.items()}}
    path = args.state.resolve().parent / 'model_protocol.json'
    path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')

    # Same graphs, transport, persistence and lifecycle as the normal server.
    from oceanx.research.server import main as run_server
    run_server()


if __name__ == '__main__':
    main()
