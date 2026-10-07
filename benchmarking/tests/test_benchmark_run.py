""".env-only launch, immutable shared inputs and concurrent starts; no API calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import errno
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark_config import load_config, ROOT
from benchmark_run import configure_run, experiment_guard, shared_queries, reset_experiment
from oceanx.batch import load_queries
from test_prepare_queries import archive as archive


@pytest.fixture
def configured(archive, tmp_path):
    file = tmp_path / '.env'
    file.write_text(f'DEEPSEEK_API_KEY=private-test-key\nBENCH_DATA_ROOT={archive}\n'
                    f'BENCH_OUTPUT_ROOT={tmp_path / "results"}\nBENCH_EXPERIMENT=pilot-r1\n'
                    'BENCH_TASKS=Q07,Q08\n')
    return file


def test_template_contains_all_launch_settings_and_an_empty_key():
    config = load_config(ROOT / 'benchmarking/.env.example')
    assert config.run['BENCH_DATA_ROOT'] == '/import/home3/share/mafzhang'
    assert config.run['BENCH_TASKS'] == 'available'
    assert config.run['BENCH_FINCH_PYTHON'].endswith('/finch-bench/bin/python')
    assert config.run['BENCH_FINCH_EXECUTION_TIMEOUT'] == '1200'
    assert config.run['BENCH_CLAUDE_ALLOW_TOOLS']
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        config.endpoint('openai')


def test_template_sets_the_expert_call_limit_under_test():
    template = ROOT / 'benchmarking/.env.example'
    assert 'BENCH_OCEANX_EXPERT_CALL_LIMIT=40' in template.read_text().splitlines()  # written out, not defaulted
    assert load_config(template).run['BENCH_OCEANX_EXPERT_CALL_LIMIT'] == '40'


def test_template_allows_three_data_experts_at_once():
    template = ROOT / 'benchmarking/.env.example'
    assert 'BENCH_OCEANX_MAX_PARALLEL_EXPERTS=3' in template.read_text().splitlines()  # written out, not defaulted
    assert load_config(template).run['BENCH_OCEANX_MAX_PARALLEL_EXPERTS'] == '3'


@pytest.mark.parametrize('line, expected', [('', '3'), ('BENCH_OCEANX_MAX_PARALLEL_EXPERTS=2\n', '2'),
                                            ('BENCH_OCEANX_MAX_PARALLEL_EXPERTS=4\n', '4')])
def test_data_expert_slots_reach_the_backend_environment(configured, monkeypatch, line, expected):
    monkeypatch.setenv('OCEANX_MAX_PARALLEL_EXPERTS', '2')  # restored afterwards; configure_run overwrites it
    configured.write_text(configured.read_text() + line)
    configure_run(oceanx_args(), load_config(configured), 'OceanX')
    assert os.environ['OCEANX_MAX_PARALLEL_EXPERTS'] == expected


def test_zero_data_expert_slots_is_refused(configured, monkeypatch):
    monkeypatch.setenv('OCEANX_MAX_PARALLEL_EXPERTS', '2')
    configured.write_text(configured.read_text() + 'BENCH_OCEANX_MAX_PARALLEL_EXPERTS=0\n')
    with pytest.raises(ValueError, match='BENCH_OCEANX_MAX_PARALLEL_EXPERTS'):
        configure_run(oceanx_args(), load_config(configured), 'OceanX')


def oceanx_args():
    return SimpleNamespace(queries=None, output=None, resume=None, arm=None, library=None, timeout=None)


@pytest.mark.parametrize('line, expected', [('', '40'), ('BENCH_OCEANX_EXPERT_CALL_LIMIT=30\n', '30'),
                                            ('BENCH_OCEANX_EXPERT_CALL_LIMIT=10\n', '10'),
                                            ('BENCH_OCEANX_EXPERT_CALL_LIMIT=60\n', '60')])
def test_expert_call_limit_reaches_the_backend_environment(configured, monkeypatch, line, expected):
    monkeypatch.setenv('OCEANX_EXPERT_CALL_LIMIT', '60')  # restored afterwards; configure_run overwrites it
    configured.write_text(configured.read_text() + line)
    configure_run(oceanx_args(), load_config(configured), 'OceanX')
    assert os.environ['OCEANX_EXPERT_CALL_LIMIT'] == expected


@pytest.mark.parametrize('value', ['9', '0', '61', 'forty'])
def test_expert_call_limit_stays_between_ten_and_the_desktop_limit(configured, monkeypatch, value):
    monkeypatch.setenv('OCEANX_EXPERT_CALL_LIMIT', '60')
    configured.write_text(configured.read_text() + f'BENCH_OCEANX_EXPERT_CALL_LIMIT={value}\n')
    with pytest.raises(ValueError, match='BENCH_OCEANX_EXPERT_CALL_LIMIT'):
        configure_run(oceanx_args(), load_config(configured), 'OceanX')


def test_concurrent_methods_share_one_selection(configured):
    config = load_config(configured)
    with ThreadPoolExecutor(max_workers=3) as pool:
        selections = list(pool.map(lambda _: shared_queries(config), range(3)))
    assert len(set(selections)) == 1
    queries, outputs = selections[0]
    assert [c.id for c in load_queries(queries)] == ['Q07', 'Q08']
    assert outputs == configured.parent / 'results/pilot-r1/runs'
    record = json.loads(queries.with_name('selection.json').read_text())
    assert record['task_ids'] == ['Q07', 'Q08']
    assert 'private-test-key' not in json.dumps(record)
    assert not list(outputs.parent.rglob('*.nc'))


def test_available_is_frozen_even_when_more_data_arrive(configured, archive):
    configured.write_text(configured.read_text().replace('BENCH_TASKS=Q07,Q08', 'BENCH_TASKS=available'))
    coverage = archive / '_download_all/coverage.json'
    doc = json.loads(coverage.read_text())
    doc['tasks']['Q09']['numerical_inputs_complete'] = False
    doc['tasks']['Q09']['missing_groups'] = ['P_GULF']
    coverage.write_text(json.dumps(doc))
    queries, _ = shared_queries(load_config(configured))
    original = queries.read_bytes()
    assert 'Q09' not in [c.id for c in load_queries(queries)]
    doc['tasks']['Q09']['numerical_inputs_complete'] = True
    coverage.write_text(json.dumps(doc))
    assert shared_queries(load_config(configured))[0].read_bytes() == original


@pytest.mark.parametrize('change', ['BENCH_MODEL=changed', 'BENCH_TIMEOUT_SECONDS=120',
                                   'BENCH_TASKS=Q07', 'BENCH_FINCH_MAX_STEPS=30'])
def test_changed_configuration_cannot_reuse_an_experiment(configured, change):
    shared_queries(load_config(configured))
    field = change.split('=')[0]
    content = '\n'.join(line for line in configured.read_text().splitlines() if not line.startswith(field + '='))
    configured.write_text(content + '\n' + change + '\n')
    with pytest.raises(ValueError, match='new BENCH_EXPERIMENT'):
        shared_queries(load_config(configured))


def test_resume_and_key_rotation_do_not_change_the_selection(configured):
    original = shared_queries(load_config(configured))
    configured.write_text(configured.read_text().replace('private-test-key', 'rotated-test-key')
                          + 'BENCH_RESUME=true\n')
    assert shared_queries(load_config(configured)) == original


def test_corrupted_queries_fail_instead_of_regenerating(configured):
    queries, _ = shared_queries(load_config(configured))
    queries.write_text(queries.read_text() + '\n')
    with pytest.raises(ValueError, match='inputs/config changed'):
        shared_queries(load_config(configured))


@pytest.mark.parametrize('change', ['BENCH_TASKS=Q07,Q07', 'BENCH_TASKS=E01', 'BENCH_TASKS=',
                                   'BENCH_EXPERIMENT=../bad', 'BENCH_TIMEOUT_SECONDS=nan',
                                   'BENCH_SUITE=test\nBENCH_EVOLUTION_SET=A'])
def test_invalid_selection_fails_without_a_query_file(configured, change):
    field = change.split('=')[0]
    content = '\n'.join(line for line in configured.read_text().splitlines() if not line.startswith(field + '='))
    configured.write_text(content + '\n' + change + '\n')
    with pytest.raises(ValueError):
        shared_queries(load_config(configured))
    assert not list(configured.parent.rglob('queries.jsonl'))


def test_results_cannot_be_inside_input_data(configured, archive):
    configured.write_text(configured.read_text().replace(str(configured.parent / 'results'), str(archive / 'runs')))
    with pytest.raises(ValueError, match='separate'):
        shared_queries(load_config(configured))
    assert not (archive / 'runs').exists()


def test_evolution_set_and_space_separated_tasks(configured):
    configured.write_text(configured.read_text().replace('BENCH_TASKS=Q07,Q08',
                          'BENCH_SUITE=evolution\nBENCH_EVOLUTION_SET=B\nBENCH_TASKS=E17 E18'))
    queries, _ = shared_queries(load_config(configured))
    assert [c.id for c in load_queries(queries)] == ['E17', 'E18']


def test_no_argument_oceanx_launch(configured, monkeypatch):
    import benchmark_config
    import run_oceanx
    monkeypatch.setenv('OCEANX_EXPERT_CALL_LIMIT', '60')  # restored afterwards; the launch sets it
    monkeypatch.setenv('OCEANX_MAX_PARALLEL_EXPERTS', '2')
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    monkeypatch.setenv('OCEANX_RESEARCH_POLICY', 'v0-coordinator-bfs')
    monkeypatch.setattr(benchmark_config, 'preflight', lambda **_: None)
    monkeypatch.setattr(run_oceanx, 'LIBRARY', None)
    monkeypatch.setattr(run_oceanx, 'ARM', {})
    monkeypatch.setattr(run_oceanx.batch, 'BatchClient', run_oceanx.batch.BatchClient)
    monkeypatch.setattr(run_oceanx.batch, 'interaction_answer', run_oceanx.batch.interaction_answer)
    observed = {}
    async def batch(cases, output, resume):
        observed.update(ids=[c.id for c in cases], output=output, resume=resume)
        return [{'status': 'completed'}]
    monkeypatch.setattr(run_oceanx.batch, 'run_batch', batch)
    with pytest.raises(SystemExit) as exc:
        run_oceanx.main([])
    assert exc.value.code == 0
    assert observed == {'ids': ['Q07', 'Q08'], 'output': configured.parent / 'results/pilot-r1/runs/OceanX',
                        'resume': False}
    assert run_oceanx.ARM['policy'] == 'v2-nested'
    assert os.environ['OCEANX_EXPERT_CALL_LIMIT'] == '40'  # the benchmark's setting, not the desktop's 60
    assert os.environ['OCEANX_MAX_PARALLEL_EXPERTS'] == '3'  # the benchmark runs three data Experts at once


@pytest.fixture
def shared(configured, monkeypatch):
    """The shared benchmarking/.env of a checkout, with no settings file named any other way."""
    import benchmark_config
    monkeypatch.setattr(benchmark_config, 'DEFAULT_CONFIG', configured)
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', 'restored after the test')
    monkeypatch.delenv('OCEAN_BENCH_CONFIG')
    return configured.resolve()


def own_settings(shared, method, experiment):
    path = shared.with_name(f'.env.{method}')
    path.write_text(shared.read_text().replace('BENCH_EXPERIMENT=pilot-r1', f'BENCH_EXPERIMENT={experiment}'))
    return path


def test_a_runner_loads_its_own_settings_file_when_it_has_one(shared, capsys):
    from benchmark_config import load_runner_config
    assert load_runner_config('OceanX').source == shared  # none of its own: the shared file, as before
    own = own_settings(shared, 'oceanx', 'oceanx-r2')
    config = load_runner_config('OceanX')
    assert config.source == own and config.run['BENCH_EXPERIMENT'] == 'oceanx-r2'
    # Another runner does not read OceanX's file.
    other = load_runner_config('Claude')
    assert other.source == shared and other.run['BENCH_EXPERIMENT'] == 'pilot-r1'
    said = capsys.readouterr().out
    assert f'OceanX settings: {own}' in said and f'Claude settings: {shared}' in said


def test_a_named_file_or_the_environment_comes_before_a_runners_own_file(shared, monkeypatch, tmp_path):
    from benchmark_config import load_runner_config
    own_settings(shared, 'finch', 'finch-r2')
    named = tmp_path / 'named.env'
    named.write_text(shared.read_text().replace('pilot-r1', 'named-r1'))
    assert load_runner_config('Finch', named).run['BENCH_EXPERIMENT'] == 'named-r1'
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(named))
    assert load_runner_config('Finch').run['BENCH_EXPERIMENT'] == 'named-r1'
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', '')  # an empty value names nothing
    assert load_runner_config('Finch').run['BENCH_EXPERIMENT'] == 'finch-r2'
    assert load_runner_config('Claude').source == shared  # no file of its own: the shared one


def test_an_error_in_a_runners_own_file_follows_the_line_that_names_the_file(shared, capsys):
    from benchmark_config import load_runner_config
    own = shared.with_name('.env.claude')
    own.write_text('NOT_A_SETTING=1\n')
    with pytest.raises(ValueError, match='unsupported fields'):
        load_runner_config('Claude')
    assert f'Claude settings: {own}' in capsys.readouterr().out


def test_oceanx_runs_its_own_experiment_and_hands_its_file_to_its_server_processes(shared, monkeypatch):
    import benchmark_config
    import run_oceanx
    own = own_settings(shared, 'oceanx', 'oceanx-r2')
    own.write_text(own.read_text() + 'BENCH_RESUME=true\n')
    for name in ('OCEANX_EXPERT_CALL_LIMIT', 'OCEANX_MAX_PARALLEL_EXPERTS', 'OCEANX_RESEARCH_POLICY',
                 'OCEANX_MAX_PARALLEL_SEARCH_EXPERTS'):
        monkeypatch.setenv(name, os.environ.get(name, '1'))  # restored afterwards; the launch sets them
    monkeypatch.setattr(benchmark_config, 'preflight', lambda **_: None)
    monkeypatch.setattr(run_oceanx, 'LIBRARY', None)
    monkeypatch.setattr(run_oceanx, 'ARM', {})
    monkeypatch.setattr(run_oceanx.batch, 'BatchClient', run_oceanx.batch.BatchClient)
    monkeypatch.setattr(run_oceanx.batch, 'interaction_answer', run_oceanx.batch.interaction_answer)
    observed = {}

    async def batch(cases, output, resume):
        observed.update(ids=[c.id for c in cases], output=output, resume=resume)
        return [{'status': 'completed'}]

    monkeypatch.setattr(run_oceanx.batch, 'run_batch', batch)
    with pytest.raises(SystemExit) as exc:
        run_oceanx.main([])
    assert exc.value.code == 0
    # Its own experiment; nothing was started under the shared file's experiment.
    assert observed['output'] == shared.parent / 'results/oceanx-r2/runs/OceanX'
    assert not (shared.parent / 'results/pilot-r1').exists()
    # The backend and the Agent Server of every case read the same file again.
    assert os.environ['OCEAN_BENCH_CONFIG'] == str(own)


def test_distinct_method_output_names_are_required(configured):
    configured.write_text(configured.read_text() + 'BENCH_CLAUDE_ARM=OceanX\n')
    with pytest.raises(ValueError, match='distinct'):
        shared_queries(load_config(configured))


def test_shared_resume_starts_an_unstarted_method(configured):
    configured.write_text(configured.read_text() + 'BENCH_RESUME=true\n')
    args = SimpleNamespace(queries=None, output=None, resume=None, arm=None, claude=None, allow_tools=None)
    configure_run(args, load_config(configured), 'Claude')
    assert args.resume is False
    args.output.mkdir(parents=True)
    other = SimpleNamespace(queries=None, output=None, resume=None, arm=None, claude=None, allow_tools=None)
    configure_run(other, load_config(configured), 'Claude')
    assert other.resume is True


def test_explicit_cli_still_works_without_shared_roots(configured):
    file = configured.parent / 'minimal.env'
    file.write_text('DEEPSEEK_API_KEY=test-key\n')
    args = SimpleNamespace(queries=Path('explicit.jsonl'), output=Path('explicit-output'),
                           resume=None, arm=None, claude=None, allow_tools=None)
    configure_run(args, load_config(file), 'Claude')
    assert args.queries == Path('explicit.jsonl') and args.output == Path('explicit-output')
    assert args.claude == 'claude' and args.allow_tools == [] and not args.resume


@pytest.mark.parametrize('damage', ['config', 'queries', 'missing_manifest'])
def test_reset_reuses_name_after_errors_without_mixing_old_results(configured, damage):
    queries, runs = shared_queries(load_config(configured))
    old_input = queries.read_bytes()
    result = runs / 'Finch/Q07/attempt-failed/result.json'
    result.parent.mkdir(parents=True)
    result.write_text('{"status":"failed"}')
    if damage == 'config':
        configured.write_text(configured.read_text().replace('BENCH_TASKS=Q07,Q08', 'BENCH_TASKS=Q07'))
    elif damage == 'queries':
        queries.write_text('corrupted')
    else:
        queries.with_name('selection.json').unlink()
    config = load_config(configured)
    archived = reset_experiment(config)
    assert archived.parent == runs.parent.parent / '.archive'
    assert (archived / 'runs/Finch/Q07/attempt-failed/result.json').read_text() == '{"status":"failed"}'
    assert not runs.parent.exists()
    new_queries, new_runs = shared_queries(config)
    assert new_queries == queries and new_runs == runs
    assert not list(new_runs.glob('*/Q07/attempt-*/result.json'))
    assert [c.id for c in load_queries(new_queries)] == (['Q07'] if damage == 'config' else ['Q07', 'Q08'])
    if damage == 'config':
        assert (archived / 'inputs/queries.jsonl').read_bytes() == old_input


def test_reset_does_not_create_an_absent_experiment(configured):
    assert reset_experiment(load_config(configured)) is None
    assert not (configured.parent / 'results/pilot-r1').exists()


@pytest.mark.parametrize('reset', [False, True])
def test_experiment_guard_uses_nfs_compatible_file_access(configured, monkeypatch, reset):
    """NFS emulates flock with locks requiring readable/shared, writable/exclusive FDs."""
    original = fcntl.flock
    operations = []

    def nfs_flock(file, operation):
        access = fcntl.fcntl(file.fileno(), fcntl.F_GETFL) & os.O_ACCMODE
        if ((operation & fcntl.LOCK_SH and access == os.O_WRONLY)
                or (operation & fcntl.LOCK_EX and access == os.O_RDONLY)):
            raise OSError(errno.EBADF, 'Bad file descriptor')
        operations.append(operation)
        return original(file, operation)

    monkeypatch.setattr(fcntl, 'flock', nfs_flock)
    with experiment_guard(load_config(configured), reset=reset) as experiment:
        assert experiment == configured.parent / 'results/pilot-r1'
    expected = (fcntl.LOCK_EX if reset else fcntl.LOCK_SH) | fcntl.LOCK_NB
    assert operations == [expected]


def test_concurrent_launch_leases_block_reset_until_every_runner_exits(configured):
    config = load_config(configured)
    with ExitStack() as stack:
        for _ in range(3):
            args = SimpleNamespace(queries=None, output=None, resume=None, arm=None, claude=None, allow_tools=None)
            configure_run(args, config, 'Claude', stack=stack)
        with pytest.raises(ValueError, match='Experiment is running'):
            reset_experiment(config)
    assert reset_experiment(config).is_dir()


def test_reset_respects_older_runner_locks(configured):
    _, runs = shared_queries(load_config(configured))
    path = runs / 'Finch/.runner.lock'
    path.parent.mkdir(parents=True)
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='Experiment is running'):
            reset_experiment(load_config(configured))
    oceanx = runs / 'OceanX/.runner.lock'
    oceanx.parent.mkdir()
    oceanx.write_text('12345')
    with pytest.raises(ValueError, match='Runner lock exists'):
        reset_experiment(load_config(configured))
    oceanx.unlink()
    assert reset_experiment(load_config(configured)).is_dir()
