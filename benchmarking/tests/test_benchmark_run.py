"""Launches from a settings file: questions chosen at every launch, an experiment that continues; no API calls."""
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark_config import load_config, ROOT
from benchmark_run import attempts, configure_run, load_cases, record_launch, runner_lock
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


def launch(settings, method='Claude'):
    """The arguments of one launch with no command-line options, after the settings file filled them."""
    args = SimpleNamespace(queries=None, output=None, resume=None, arm=None, claude=None, allow_tools=None,
                           library=None, timeout=None)
    configure_run(args, load_config(settings), method)
    return args


def edit(settings, change):
    """Replace one setting (or add it)."""
    field = change.split('=')[0]
    kept = [line for line in settings.read_text().splitlines() if not line.startswith(field + '=')]
    settings.write_text('\n'.join(kept) + '\n' + change + '\n')


def finished(output, task, status, name='attempt-1'):
    result = output / task / name / 'result.json'
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({'id': task, 'status': status}))
    return result.parent


def test_a_launch_chooses_its_questions_from_the_settings_and_creates_nothing(configured):
    args = launch(configured)
    assert [case.id for case in load_cases(args)] == ['Q07', 'Q08']
    assert args.output == configured.parent / 'results/pilot-r1/runs/Claude'
    assert args.resume is True  # continuing is the default
    assert not (configured.parent / 'results').exists()
    # Another method of the same experiment gets the same questions and a folder of its own.
    other = launch(configured, 'OceanX')
    assert other.cases == args.cases and other.output == args.output.with_name('OceanX')


def test_a_question_whose_data_arrive_later_runs_on_the_next_launch(configured, archive, capsys):
    edit(configured, 'BENCH_TASKS=available')
    coverage = archive / '_download_all/coverage.json'
    doc = json.loads(coverage.read_text())
    doc['tasks']['Q09'] = {'numerical_inputs_complete': False, 'missing_groups': ['P_GULF']}
    coverage.write_text(json.dumps(doc))
    first = launch(configured)
    ids = [case['id'] for case in first.cases]
    assert 'Q09' not in ids and len(ids) == 29
    assert "Q09: excluded; missing groups: ['P_GULF']" in capsys.readouterr().out
    for task in ids:
        finished(first.output, task, 'completed')
    # The data arrive. The same experiment, launched again, runs the question that was left out.
    doc['tasks']['Q09'] = {'numerical_inputs_complete': True, 'missing_groups': []}
    coverage.write_text(json.dumps(doc))
    second = launch(configured)
    assert second.output == first.output and len(second.cases) == 30
    todo = list(attempts(load_cases(second), second.output, second.resume))
    assert [case.id for case, _ in todo] == ['Q09']


@pytest.mark.parametrize('change', ['BENCH_MODEL=changed', 'BENCH_TIMEOUT_SECONDS=120',
                                    'BENCH_TASKS=Q07', 'BENCH_FINCH_MAX_STEPS=30'])
def test_an_experiment_continues_after_its_settings_change(configured, change):
    first = launch(configured)
    finished(first.output, 'Q07', 'completed')
    edit(configured, change)
    second = launch(configured)
    assert second.output == first.output
    cases = load_cases(second)
    assert [case.id for case in cases] == (['Q07'] if change == 'BENCH_TASKS=Q07' else ['Q07', 'Q08'])
    assert cases[0].timeout_seconds == (120 if 'TIMEOUT' in change else 10800)
    assert [case.id for case, _ in attempts(cases, second.output, second.resume)] == (
        [] if change == 'BENCH_TASKS=Q07' else ['Q08'])


@pytest.mark.parametrize('change', ['BENCH_TASKS=Q07,Q07', 'BENCH_TASKS=E01', 'BENCH_TASKS=',
                                    'BENCH_EXPERIMENT=../bad', 'BENCH_TIMEOUT_SECONDS=nan',
                                    'BENCH_SUITE=test\nBENCH_EVOLUTION_SET=A', 'BENCH_RESUME=maybe'])
def test_invalid_settings_stop_the_launch_before_anything_is_created(configured, change):
    edit(configured, change)
    with pytest.raises(ValueError):
        launch(configured)
    assert not (configured.parent / 'results').exists()


def test_results_cannot_be_inside_input_data(configured, archive):
    configured.write_text(configured.read_text().replace(str(configured.parent / 'results'), str(archive / 'runs')))
    with pytest.raises(ValueError, match='separate'):
        launch(configured)
    assert not (archive / 'runs').exists()


def test_evolution_set_and_space_separated_tasks(configured):
    configured.write_text(configured.read_text().replace('BENCH_TASKS=Q07,Q08',
                          'BENCH_SUITE=evolution\nBENCH_EVOLUTION_SET=B\nBENCH_TASKS=E17 E18'))
    assert [case.id for case in load_cases(launch(configured))] == ['E17', 'E18']


def test_resume_skips_completed_questions_and_gives_the_others_a_new_attempt(tmp_path, capsys):
    cases = [SimpleNamespace(id=task) for task in ('Q07', 'Q08', 'Q09', 'Q10')]
    finished(tmp_path, 'Q07', 'completed')
    failed = finished(tmp_path, 'Q08', 'failed')
    # The latest attempt decides: a completed one after a failure, and a failure after a completed one.
    finished(tmp_path, 'Q09', 'timed_out', 'attempt-1')
    finished(tmp_path, 'Q09', 'completed', 'attempt-2')
    todo = {case.id: folder for case, folder in attempts(cases, tmp_path, resume=True)}
    assert list(todo) == ['Q08', 'Q10']
    assert capsys.readouterr().out.splitlines() == ['[Q07] skipped (completed)', '[Q09] skipped (completed)']
    assert todo['Q08'].parent == tmp_path / 'Q08' and todo['Q08'].name.startswith('attempt-')
    assert not todo['Q08'].exists() and failed.is_dir()  # the runner creates it; the failed one stays
    finished(tmp_path, 'Q07', 'failed', 'attempt-2')
    assert [case.id for case, _ in attempts(cases[:1], tmp_path, resume=True)] == ['Q07']


def test_without_resume_the_chosen_questions_run_again_and_earlier_attempts_stay(tmp_path, capsys):
    cases = [SimpleNamespace(id=task) for task in ('Q25', 'Q27')]
    earlier = finished(tmp_path, 'Q25', 'completed', 'attempt-1700000000000000000-aaaaaaaa')
    todo = {case.id: folder for case, folder in attempts(cases, tmp_path, resume=False)}
    assert list(todo) == ['Q25', 'Q27'] and capsys.readouterr().out == ''
    assert earlier.is_dir()
    # The evaluation reads the last attempt in name order, which is the new one.
    assert max(earlier.name, todo['Q25'].name) == todo['Q25'].name


def test_one_runner_per_method_folder(tmp_path):
    with runner_lock(tmp_path), pytest.raises(ValueError, match='Another runner is writing'):
        runner_lock(tmp_path).__enter__()  # a second runner asks for the same folder
    with runner_lock(tmp_path):  # free again
        pass
    # A lock file left by a runner that crashed, or by an older OceanX runner (its process number), locks nothing.
    (tmp_path / '.runner.lock').write_text('12345')
    with runner_lock(tmp_path):
        pass


def test_the_runner_lock_works_on_nfs(tmp_path, monkeypatch):
    """NFS emulates flock with locks that need a writable descriptor for an exclusive lock."""
    original = fcntl.flock

    def nfs_flock(file, operation):
        access = fcntl.fcntl(file.fileno(), fcntl.F_GETFL) & os.O_ACCMODE
        if operation & fcntl.LOCK_EX and access == os.O_RDONLY:
            raise OSError(errno.EBADF, 'Bad file descriptor')
        return original(file, operation)

    monkeypatch.setattr(fcntl, 'flock', nfs_flock)
    with runner_lock(tmp_path):
        pass


def test_every_launch_is_recorded_without_the_key(configured, tmp_path):
    args = launch(configured)
    cases = load_cases(args)
    record_launch(tmp_path, 'Claude', load_config(configured), cases, True, cli_version='1.0')
    edit(configured, 'BENCH_TASKS=Q08')
    record_launch(tmp_path, 'Claude', load_config(configured), cases[1:], False)
    text = (tmp_path / 'launches.jsonl').read_text()
    first, second = (json.loads(line) for line in text.splitlines())
    assert first['method'] == 'Claude' and first['tasks'] == ['Q07', 'Q08'] and first['resume'] is True
    assert first['cli_version'] == '1.0' and first['started_utc'] <= second['started_utc']
    assert set(first) >= {'commit', 'dirty', 'sources_sha256', 'model', 'settings'}
    code = hashlib.sha256()  # the runner files, names and contents: the same value means the same code
    for path in sorted((ROOT / 'benchmarking/server').glob('*.py')):
        code.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    assert first['sources_sha256'] == second['sources_sha256'] == code.hexdigest()
    assert first['settings']['BENCH_TASKS'] == 'Q07,Q08' and second['settings']['BENCH_TASKS'] == 'Q08'
    assert second['tasks'] == ['Q08'] and second['resume'] is False
    assert 'private-test-key' not in text


@pytest.fixture
def oceanx_entry(monkeypatch):
    """run_oceanx without the sandbox check and with a collector that only notes its calls."""
    import benchmark_config
    import collect_oceanx
    import run_oceanx
    for name in ('OCEANX_EXPERT_CALL_LIMIT', 'OCEANX_MAX_PARALLEL_EXPERTS', 'OCEANX_RESEARCH_POLICY',
                 'OCEANX_MAX_PARALLEL_SEARCH_EXPERTS', 'OCEAN_BENCH_CONFIG'):
        monkeypatch.setenv(name, os.environ.get(name, '1'))  # restored afterwards; the launch sets them
    monkeypatch.setattr(benchmark_config, 'preflight', lambda **_: None)
    monkeypatch.setattr(run_oceanx, 'LIBRARY', None)
    monkeypatch.setattr(run_oceanx, 'ARM', {})
    monkeypatch.setattr(run_oceanx.batch, 'BatchClient', run_oceanx.batch.BatchClient)
    monkeypatch.setattr(run_oceanx.batch, 'interaction_answer', run_oceanx.batch.interaction_answer)
    collected = []
    monkeypatch.setattr(collect_oceanx, 'collect_run', lambda output: collected.append(output) or 'collection-1')

    def run(*argv):
        with pytest.raises(SystemExit) as stopped:
            run_oceanx.main(list(argv))
        return stopped.value.code

    return SimpleNamespace(module=run_oceanx, run=run, collected=collected)


@pytest.fixture
def oceanx(oceanx_entry, monkeypatch):
    """Also without a backend: every question it starts is noted and ends with the status in `outcome`."""
    started, outcome = [], {}

    async def run_case(case, directory):
        started.append((case.id, directory))
        return {'id': case.id, 'status': outcome.get(case.id, 'completed')}

    monkeypatch.setattr(oceanx_entry.module.batch, 'run_case', run_case)
    oceanx_entry.started, oceanx_entry.outcome = started, outcome
    return oceanx_entry


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_no_argument_oceanx_launch(configured, monkeypatch, oceanx):
    monkeypatch.setenv('OCEANX_EXPERT_CALL_LIMIT', '60')
    monkeypatch.setenv('OCEANX_MAX_PARALLEL_EXPERTS', '2')
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    monkeypatch.setenv('OCEANX_RESEARCH_POLICY', 'v0-coordinator-bfs')
    assert oceanx.run() == 0
    output = configured.parent / 'results/pilot-r1/runs/OceanX'
    assert [task for task, _ in oceanx.started] == ['Q07', 'Q08']
    assert all(folder.parent == output / task and folder.name.startswith('attempt-')
               for task, folder in oceanx.started)
    assert oceanx.module.ARM['policy'] == 'v2-nested'
    assert os.environ['OCEANX_EXPERT_CALL_LIMIT'] == '40'  # the benchmark's setting, not the desktop's 60
    assert os.environ['OCEANX_MAX_PARALLEL_EXPERTS'] == '3'  # the benchmark runs three data Experts at once
    assert [result['id'] for result in records(output / 'results.jsonl')] == ['Q07', 'Q08']
    [said] = records(output / 'launches.jsonl')
    assert (said['method'], said['tasks'], said['resume']) == ('OceanX', ['Q07', 'Q08'], True)
    assert said['arm']['policy'] == 'v2-nested' and said['arm']['figure_delivery'] == 'static'
    assert 'private-test-key' not in json.dumps(said)


def test_oceanx_continues_an_experiment_that_other_code_and_settings_started(configured, monkeypatch, oceanx):
    """What stopped the reruns of 2026-10-07. The experiment kept the hashes of the runner files of the
    day it was made, and the method folder a fingerprint of its questions; neither is compared now."""
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    experiment = configured.parent / 'results/pilot-r1'
    output = experiment / 'runs/OceanX'
    finished(output, 'Q07', 'completed')
    finished(output, 'Q08', 'failed')
    (experiment / 'inputs').mkdir()
    (experiment / 'inputs/selection.json').write_text(json.dumps(
        {'identity': {'runner_sources_sha256': {'run_oceanx.py': 'of older code'}}, 'task_ids': ['Q07']}))
    (output / 'manifest.json').write_text(json.dumps({'fingerprint': 'of other questions'}))
    (output / '.runner.lock').write_text('12345')  # a crashed older runner left its process number
    (output / 'arm.json').write_text(json.dumps(
        {'arm': 'OceanX', 'policy': 'v2-nested', 'library': None, 'commit': 'older'}))
    oceanx.outcome['Q08'] = 'failed'
    assert oceanx.run() == 1  # a question that did not complete is still reported by the exit status
    assert [task for task, _ in oceanx.started] == ['Q08']  # the completed one is skipped
    assert json.loads((output / 'arm.json').read_text())['commit'] == 'older'  # written once, at the start
    assert len(records(output / 'launches.jsonl')) == 1
    # Chosen again without resume, a completed question runs again. Nothing is removed.
    edit(configured, 'BENCH_TASKS=Q07')
    edit(configured, 'BENCH_RESUME=false')
    assert oceanx.run() == 0
    assert [task for task, _ in oceanx.started] == ['Q08', 'Q07']
    assert (output / 'Q07/attempt-1/result.json').is_file()
    assert [said['resume'] for said in records(output / 'launches.jsonl')] == [True, False]


class FakeBackend:
    """In place of the backend of one attempt: the questions named in `crash` lose it, the others answer."""
    crash = frozenset()

    def __init__(self, directory, case):
        self.directory, self.case, self.context, self.events_truncated = directory, case, {'task_id': 't1'}, False

    async def start(self):
        pass

    async def analyze(self):
        if self.case.id in self.crash:
            raise RuntimeError('backend disconnected')
        return {'type': 'request.completed', 'payload': {'result': {'assistant_text': 'Final answer'}}}

    async def request(self, kind, payload):
        return {'payload': {'result': {'outputs': []}}}

    async def close(self):
        pass


def test_oceanx_runs_every_question_keeps_each_result_and_collects_once(configured, monkeypatch, oceanx_entry):
    """Through OceanX's own function for one question; only the backend process is replaced."""
    import signal
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    monkeypatch.setattr(oceanx_entry.module, 'BenchmarkClient', FakeBackend)
    monkeypatch.setattr(FakeBackend, 'crash', {'Q07'})
    handler = signal.getsignal(signal.SIGTERM)
    assert oceanx_entry.run() == 1
    assert signal.getsignal(signal.SIGTERM) is handler
    output = configured.parent / 'results/pilot-r1/runs/OceanX'
    first, second = records(output / 'results.jsonl')
    assert (first['id'], first['status'], second['id'], second['status']) == ('Q07', 'failed', 'Q08', 'completed')
    assert 'backend disconnected' in first['error']  # one lost backend does not stop the next question
    for result in (first, second):
        attempt = Path(result['directory'])
        assert attempt.parent == output / result['id']
        assert json.loads((attempt / 'result.json').read_text())['status'] == result['status']
        assert json.loads((attempt / 'query.json').read_text())['id'] == result['id']
    assert (Path(second['directory']) / 'answer.md').read_text() == 'Final answer'
    assert oceanx_entry.collected == [output]
    # The same command again: only the question that did not complete runs, in a new attempt.
    monkeypatch.setattr(FakeBackend, 'crash', set())
    assert oceanx_entry.run() == 0
    third = records(output / 'results.jsonl')[2]
    assert (third['id'], third['status']) == ('Q07', 'completed') and third['directory'] != first['directory']
    assert len(records(output / 'results.jsonl')) == 3 and len(records(output / 'launches.jsonl')) == 2
    assert oceanx_entry.collected == [output, output]
    # Nothing left to do: the launch says so by its exit status and starts nothing.
    assert oceanx_entry.run() == 0 and len(records(output / 'results.jsonl')) == 3


def test_a_second_oceanx_runner_on_the_same_folder_starts_and_collects_nothing(configured, monkeypatch, oceanx):
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    output = configured.parent / 'results/pilot-r1/runs/OceanX'
    finished(output, 'Q07', 'completed')
    # The first runner is still at work.
    with runner_lock(output), pytest.raises(ValueError, match='Another runner is writing'):
        oceanx.module.main([])
    assert oceanx.started == [] and oceanx.collected == []
    assert not (output / 'launches.jsonl').exists()


def test_oceanx_keeps_an_arm_folder_to_one_arm(configured, monkeypatch, oceanx):
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(configured))
    output = configured.parent / 'results/pilot-r1/runs/OceanX'
    output.mkdir(parents=True)
    (output / 'arm.json').write_text(json.dumps({'arm': 'OceanX', 'policy': 'v0-coordinator-bfs', 'library': None}))
    assert 'different arm' in str(oceanx.run())
    assert oceanx.started == []


def test_oceanx_results_cannot_be_written_into_a_data_folder(configured, archive, oceanx, tmp_path):
    queries = tmp_path / 'explicit.jsonl'
    source = archive / 'CMEMS_Gulf'
    queries.write_text(json.dumps({'id': 'Q07', 'query': 'q', 'datasets': [str(source)]}) + '\n')
    with pytest.raises(ValueError, match='separate'):
        oceanx.module.main(['--config', str(configured), '--queries', str(queries),
                            '--output', str(source / 'results')])
    assert oceanx.started == [] and not (source / 'results').exists()


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


def test_oceanx_runs_its_own_experiment_and_hands_its_file_to_its_server_processes(shared, oceanx, monkeypatch):
    monkeypatch.delenv('OCEAN_BENCH_CONFIG')  # the fixture set it only to have it restored
    own = own_settings(shared, 'oceanx', 'oceanx-r2')
    assert oceanx.run() == 0
    # Its own experiment; nothing was started under the shared file's experiment.
    assert all(folder.is_relative_to(shared.parent / 'results/oceanx-r2/runs/OceanX')
               for _, folder in oceanx.started) and len(oceanx.started) == 2
    assert not (shared.parent / 'results/pilot-r1').exists()
    # The backend and the Agent Server of every case read the same file again.
    assert os.environ['OCEAN_BENCH_CONFIG'] == str(own)


def test_distinct_method_output_names_are_required(configured):
    configured.write_text(configured.read_text() + 'BENCH_CLAUDE_ARM=OceanX\n')
    with pytest.raises(ValueError, match='distinct'):
        launch(configured)


def test_explicit_cli_still_works_without_shared_roots(configured):
    file = configured.parent / 'minimal.env'
    file.write_text('DEEPSEEK_API_KEY=test-key\n')
    args = SimpleNamespace(queries=Path('explicit.jsonl'), output=Path('explicit-output'),
                           resume=None, arm=None, claude=None, allow_tools=None)
    configure_run(args, load_config(file), 'Claude')
    assert args.queries == Path('explicit.jsonl') and args.output == Path('explicit-output')
    assert args.claude == 'claude' and args.allow_tools == [] and args.resume is True
    args.resume = False  # --no-resume on the command line wins over the file
    configure_run(args, load_config(file), 'Claude')
    assert args.resume is False
