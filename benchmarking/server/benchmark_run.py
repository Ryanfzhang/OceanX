"""What one launch runs: the questions chosen from the settings file and the data present now.

An experiment is a results folder: BENCH_OUTPUT_ROOT/BENCH_EXPERIMENT/runs/<method>/<question>/attempt-*.
Nothing about it is frozen. Every launch chooses its questions again, so a question whose data arrived
later runs on the next launch, and an experiment continues after the code or the settings change.
Each launch adds one line to its method folder's launches.jsonl saying what it ran with.
"""
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
import subprocess
import sys
import time
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
    """The data root and the experiment folder, checked to be apart from code, settings and data."""
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


def select_cases(config, data):
    """The questions of this launch, from the settings and the data now present.

    BENCH_TASKS=available takes every question of the suite whose data are complete and prints the
    others; they run on a later launch, once their data are there.
    """
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
    cases = prepare_queries.prepare_selection(
        data, suite, tasks=tasks, evolution_set=subset or None,
        available_only=selector == 'available', timeout=timeout, literature_mode=literature)
    print(f"Questions ({len(cases)}): {', '.join(case['id'] for case in cases)}", flush=True)
    return cases


def load_cases(args):
    """The launch's questions as runner cases: an explicit --queries file, or the selection."""
    from oceanx.batch import QueryCase, load_queries, resolve_datasets
    if args.queries:
        return load_queries(args.queries)
    return [resolve_datasets(QueryCase.model_validate(case), ROOT) for case in args.cases]


def attempts(cases, output, resume):
    """Each question this launch runs, with the folder of its new attempt.

    With resume, a question whose latest attempt completed is skipped. Without it every chosen
    question runs again. Earlier attempts are never removed; the evaluation reads the latest one.
    """
    for case in cases:
        prior = sorted((output / case.id).glob('attempt-*/result.json'))
        if resume and prior and json.loads(prior[-1].read_text(encoding='utf-8')).get('status') == 'completed':
            print(f'[{case.id}] skipped (completed)', flush=True)
            continue
        yield case, output / case.id / f'attempt-{time.time_ns()}-{uuid4().hex[:8]}'


def append_result(output, result):
    with (output / 'results.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + '\n')


@contextmanager
def runner_lock(output):
    """One runner per method folder at a time. The system drops the lock when the process ends."""
    with (output / '.runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f'Another runner is writing {output}; wait for it or stop it') from None
        yield


def git_identity() -> dict:
    def git(*args):
        result = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    status = git('status', '--porcelain', '--untracked-files=no')
    return {'commit': git('rev-parse', 'HEAD'), 'dirty': bool(status) if status is not None else None}


def sources_sha256() -> str:
    """One hash of the benchmark's runner code: the same value means the same code."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def record_launch(output, method, config, cases, resume, **details):
    """Add this launch to <output>/launches.jsonl: when, which code, which settings, which questions.

    Nothing compares these. The record is how a reader tells afterwards what an attempt ran with:
    an attempt belongs to the last launch that started before it.
    """
    record = {'started_utc': datetime.now(UTC).isoformat(), 'method': method, **git_identity(),
              'sources_sha256': sources_sha256(), 'resume': resume, 'tasks': [case.id for case in cases],
              'model': config.public(),
              'settings': {name: setting(config, name) for name in RUN_DEFAULTS}, **details}
    with (output / 'launches.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def configure_run(args, config, method):
    """Fill what the command line left out from the settings file, and choose the questions."""
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
        data, experiment = experiment_paths(config)
        args.cases = select_cases(config, data)
        args.output = args.output or experiment / 'runs' / args.arm
    if not args.output:
        raise ValueError('With explicit --queries/--query, supply --output; otherwise configure benchmarking/.env')
    print(f'{method} output: {args.output}', flush=True)
