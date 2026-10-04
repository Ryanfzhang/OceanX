"""Shared benchmark selection and explicit reset for reuse of an experiment name."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from benchmark_config import ROOT, RUN_DEFAULTS
import prepare_queries


def setting(config, name):
    return config.run.get(name, RUN_DEFAULTS[name])


def path_value(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def number(config, name, integer=False, minimum=0, maximum=None, inclusive_min=False):
    try:
        value = (int if integer else float)(setting(config, name))
    except ValueError:
        raise ValueError(f'{name}: invalid number in benchmarking/.env') from None
    too_small = value < minimum if inclusive_min else value <= minimum
    if not math.isfinite(value) or too_small or (maximum is not None and value > maximum):
        raise ValueError(f'{name}: number out of range in benchmarking/.env')
    return value


def boolean(config, name):
    value = setting(config, name).lower()
    if value not in {'true', 'false'}:
        raise ValueError(f'{name}: use true or false in benchmarking/.env')
    return value == 'true'


def words(value):
    return [part for part in re.split(r'[,\s]+', value.strip()) if part]


def label(value, name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise ValueError(f'{name}: use a short name, not a path')
    return value


def experiment_paths(config):
    """Resolve and validate shared paths for both launches and reset."""
    data = setting(config, 'BENCH_DATA_ROOT')
    output = setting(config, 'BENCH_OUTPUT_ROOT')
    if not data or not output:
        raise ValueError('Fill BENCH_DATA_ROOT and BENCH_OUTPUT_ROOT in benchmarking/.env')
    data, output = path_value(data), path_value(output)
    if not data.is_dir() or data == Path(data.anchor):
        raise ValueError('BENCH_DATA_ROOT must be an existing dedicated data directory')
    protected = [ROOT, data]
    if config.source:
        protected.append(config.source)
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('BENCH_OUTPUT_ROOT must be separate from code, .env and input data')
    finch = setting(config, 'BENCH_FINCH_ROOT')
    if finch:
        root = path_value(finch)
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError('BENCH_OUTPUT_ROOT must be separate from the Finch checkout')
    experiment = label(setting(config, 'BENCH_EXPERIMENT'), 'BENCH_EXPERIMENT')
    arms = [label(setting(config, f'BENCH_{method}_ARM'), f'BENCH_{method}_ARM')
            for method in ('OCEANX', 'CLAUDE', 'FINCH')]
    if len(set(arms)) != 3:
        raise ValueError('OceanX, Claude and Finch must have distinct BENCH_*_ARM names')
    return data, output / experiment


@contextmanager
def experiment_guard(config, *, reset=False):
    """Keep the lock outside the directory moved by reset; hold during whole runs."""
    _, experiment = experiment_paths(config)
    locks = experiment.parent / '.experiment-locks'
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    # NFS shared locks require a readable FD; reset's exclusive lock needs writing.
    with (locks / (experiment.name + '.lock')).open('a+') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if reset else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Experiment is running or being reset; stop its runners before reset') from None
        yield experiment


def reset_experiment(config):
    """Archive the entire inactive experiment, releasing its name for a fresh run."""
    from contextlib import ExitStack

    with experiment_guard(config, reset=True) as experiment, ExitStack() as locks:
        if not experiment.exists():
            print(f'Experiment already clear: {experiment}', flush=True)
            return None
        if experiment.is_symlink() or not experiment.is_dir():
            raise ValueError('Experiment must be a regular directory, not a symlink')
        # Also protect runs started by older runners without the experiment guard.
        for path in sorted((experiment / 'runs').glob('*/.runner.lock')):
            lock = locks.enter_context(path.open('r+'))
            if lock.read().strip():
                # Older OceanX uses an exclusive PID file, not flock. Its existence
                # cannot establish whether the process on another server is dead.
                raise ValueError(f'Runner lock exists: {path}; stop the runner and clear a stale lock first')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(f'Experiment is running: {path}; stop the runner before reset') from None
        archive = experiment.parent / '.archive'
        archive.mkdir(exist_ok=True, mode=0o700)
        destination = archive / (experiment.name + '-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
                                 + '-' + uuid4().hex[:8])
        experiment.rename(destination)
        print(f'Archived previous experiment: {destination}', flush=True)
        print(f'Reuse BENCH_EXPERIMENT={experiment.name} and run the usual commands.', flush=True)
        return destination


def shared_queries(config):
    """First runner selects once; later runners reuse the same frozen selection."""
    with experiment_guard(config):
        return _shared_queries(config)


def _shared_queries(config):
    data, experiment = experiment_paths(config)
    suite, subset = setting(config, 'BENCH_SUITE'), setting(config, 'BENCH_EVOLUTION_SET')
    if suite not in {'test', 'evolution'} or subset not in {'', 'A', 'B'} or (subset and suite != 'evolution'):
        raise ValueError('Use BENCH_SUITE=test or evolution; BENCH_EVOLUTION_SET=A/B only for evolution')
    selector = setting(config, 'BENCH_TASKS')
    tasks = None if selector in {'available', 'all'} else words(selector)
    if tasks == []:
        raise ValueError('BENCH_TASKS: use available, all, or a list such as Q07,Q08')
    timeout = number(config, 'BENCH_TIMEOUT_SECONDS', maximum=604800)
    literature = setting(config, 'BENCH_LITERATURE_MODE')
    if literature not in {'search_only', 'ask_before_download', 'auto_download_open_access'}:
        raise ValueError('BENCH_LITERATURE_MODE: unknown mode')
    # Resume is operational; changing it must not change the frozen inputs.
    identity = {'model': config.public(), 'settings': {
        name: setting(config, name) for name in RUN_DEFAULTS if name != 'BENCH_RESUME'},
        'catalogue_sha256': hashlib.sha256(prepare_queries.MANIFEST.read_bytes()).hexdigest(),
        'runner_sources_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in sorted(Path(__file__).parent.glob('*.py'))},
        'queries_sha256': {task: hashlib.sha256(prepare_queries.task_file(task).read_bytes()).hexdigest()
                          for task in prepare_queries.suite_tasks(suite, subset or None)}}
    directory = experiment / 'inputs'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    queries, manifest = directory / 'queries.jsonl', directory / 'selection.json'
    with (directory / '.selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if queries.exists() or manifest.exists():
            if not queries.is_file() or not manifest.is_file():
                raise ValueError('Incomplete input selection; reset this experiment or use a new BENCH_EXPERIMENT')
            saved = json.loads(manifest.read_text())
            digest = hashlib.sha256(queries.read_bytes()).hexdigest()
            if saved.get('identity') != identity or saved.get('sha256') != digest:
                raise ValueError('Experiment inputs/config changed; reset this experiment or use a new BENCH_EXPERIMENT')
        else:
            cases = prepare_queries.prepare_selection(
                data, suite, tasks=tasks, evolution_set=subset or None,
                available_only=selector == 'available', timeout=timeout, literature_mode=literature)
            content = ''.join(json.dumps(case, ensure_ascii=False) + '\n' for case in cases)
            with queries.open('x', encoding='utf-8') as stream:
                stream.write(content)
            with manifest.open('x', encoding='utf-8') as stream:
                json.dump({'identity': identity, 'task_ids': [c['id'] for c in cases],
                           'sha256': hashlib.sha256(content.encode()).hexdigest()}, stream, indent=2)
        saved = json.loads(manifest.read_text())
    print(f"Shared tasks ({len(saved['task_ids'])}): {', '.join(saved['task_ids'])}", flush=True)
    print(f'Inputs: {queries}', flush=True)
    return queries, experiment / 'runs'


def configure_run(args, config, method, *, stack=None):
    """CLI remains available, but omission means the explicit .env setting."""
    automatic = not args.queries and not getattr(args, 'query', None)
    if args.resume is None:
        args.resume = boolean(config, 'BENCH_RESUME')
    if args.arm is None:
        args.arm = label(setting(config, f'BENCH_{method.upper()}_ARM'), f'BENCH_{method.upper()}_ARM')
    if method == 'OceanX':
        if not args.library and setting(config, 'BENCH_OCEANX_LIBRARY'):
            args.library = path_value(setting(config, 'BENCH_OCEANX_LIBRARY'))
        os.environ['OCEANX_MAX_PARALLEL_EXPERTS'] = str(number(
            config, 'BENCH_OCEANX_MAX_PARALLEL_EXPERTS', integer=True))
        os.environ['OCEANX_MAX_PARALLEL_SEARCH_EXPERTS'] = str(number(
            config, 'BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS', integer=True))
        # Lower than the desktop's 60 only; a higher limit is not a setting.
        os.environ['OCEANX_EXPERT_CALL_LIMIT'] = str(number(
            config, 'BENCH_OCEANX_EXPERT_CALL_LIMIT', integer=True, minimum=10, maximum=60,
            inclusive_min=True))
        if args.timeout is None:
            args.timeout = number(config, 'BENCH_TIMEOUT_SECONDS', maximum=604800)
    elif method == 'Claude':
        args.claude = args.claude or setting(config, 'BENCH_CLAUDE_EXECUTABLE')
        if '/' in args.claude:
            args.claude = str(path_value(args.claude))
        if args.allow_tools is None:
            args.allow_tools = words(setting(config, 'BENCH_CLAUDE_ALLOW_TOOLS'))
    elif method == 'Finch':
        args.finch_root = args.finch_root or (path_value(setting(config, 'BENCH_FINCH_ROOT'))
                                             if setting(config, 'BENCH_FINCH_ROOT') else None)
        if not args.finch_root:
            raise ValueError('Fill BENCH_FINCH_ROOT in benchmarking/.env')
        for attr, field in [('python', 'PYTHON'), ('kernel_python', 'KERNEL_PYTHON'),
                            ('finch_commit', 'COMMIT'), ('bwrap', 'BWRAP')]:
            if getattr(args, attr) is None:
                setattr(args, attr, setting(config, 'BENCH_FINCH_' + field) or None)
        args.python = args.python or sys.executable
        for attr in ('python', 'kernel_python', 'bwrap'):
            value = getattr(args, attr)
            if value and '/' in value:
                setattr(args, attr, str(path_value(value)))
        for attr, field, integer in [('max_steps', 'MAX_STEPS', True), ('memory_mb', 'MEMORY_MB', True),
                                     ('execution_timeout', 'EXECUTION_TIMEOUT', False), ('cpus', 'CPUS', False)]:
            if getattr(args, attr) is None:
                setattr(args, attr, number(config, 'BENCH_FINCH_' + field, integer=integer))
        if args.temperature is None:
            args.temperature = number(config, 'BENCH_FINCH_TEMPERATURE', maximum=2, inclusive_min=True)
        if args.timeout is None:
            args.timeout = number(config, 'BENCH_TIMEOUT_SECONDS', maximum=604800)
    if automatic:
        if getattr(args, 'dataset', []):
            raise ValueError('Use --dataset only with --query')
        if stack is not None:
            stack.enter_context(experiment_guard(config))
        args.queries, output = shared_queries(config)
        args.output = args.output or output / args.arm
        # A shared resume flag can continue one method while starting an unstarted one.
        if args.resume and not args.output.exists():
            args.resume = False
    if not args.output:
        raise ValueError('With explicit --queries/--query, supply --output; otherwise configure benchmarking/.env')
    print(f'{method} output: {args.output}', flush=True)


def main(argv=None):
    import argparse
    from benchmark_config import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='benchmarking/.env by default')
    parser.add_argument('--reset', required=True, action='store_true',
                        help='Archive the inactive experiment so its name can be reused')
    args = parser.parse_args(argv)
    reset_experiment(load_config(args.config))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f'Experiment reset stopped: {exc}', file=sys.stderr)
        sys.exit(1)
