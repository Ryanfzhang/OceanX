import hashlib
import json
import pytest

from collect_oceanx import collect_run


def test_collect_preserves_attempts_and_makes_portable_gallery(tmp_path):
    run = tmp_path / "run"
    for number, status in [(1, "timed_out"), (2, "completed")]:
        attempt = run / "Q13" / f"attempt-{number}"
        attempt.mkdir(parents=True)
        (attempt / "result.json").write_text(json.dumps({"id": "Q13", "status": status}))
    receipt = attempt / "benchmark_delivery" / "receipt1"
    receipt.mkdir(parents=True)
    png = receipt / "figure.png"
    png.write_bytes(b"test fixture image")
    record = {"path": "figure.png", "bytes": png.stat().st_size,
              "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
    (receipt / "manifest.json").write_text(json.dumps({"outputs": [{"files": [], "preview": record}]}))
    original = f"Research answer ![Figure]({png})"
    (attempt / "answer.md").write_text(original)
    collection = collect_run(run)
    summary = json.loads((collection / "summary.json").read_text())
    assert len(summary) == 2
    assert summary[0]["runtime_status"] == "timed_out"
    assert summary[0]["has_final_answer"] is False
    assert summary[1]["png_count"] == 1
    review = collection / summary[1]["review"]
    assert str(png) not in review.read_text()
    assert (review.parent / "answer.md").read_text() == original
    assert (review.parent / "delivery/receipt1/figure.png").read_bytes() == png.read_bytes()
    assert collect_run(run) != collection  # Recollection preserves the existing collection.


def test_collect_records_bad_receipt_without_faking_delivery(tmp_path):
    attempt = tmp_path / "run/Q13/attempt-1"
    receipt = attempt / "benchmark_delivery/receipt1"
    receipt.mkdir(parents=True)
    (attempt / "result.json").write_text('{"id":"Q13","status":"completed"}')
    (receipt / "manifest.json").write_text(json.dumps({"outputs": [{"files": [{
        "path": "../escape.png", "bytes": 0, "sha256": "0" * 64,
    }]}]}))
    collection = collect_run(tmp_path / "run")
    result = json.loads((collection / "summary.json").read_text())[0]
    assert result["collection_errors"]
    assert result["accepted_outputs"] == 0
    assert result["has_final_answer"] is False


def current_attempt(tmp_path):
    attempt = tmp_path / 'run/E10/attempt-1'
    root = attempt / 'workspace/OceanX Tasks/E10--123456'
    root.mkdir(parents=True)
    (root / 'task-manifest.json').write_text(json.dumps({'task': {'task_id': 'task_123456'}}))
    (attempt / 'result.json').write_text(json.dumps({
        'id': 'E10', 'status': 'completed', 'task_id': 'task_123456', 'elapsed_seconds': 12,
    }))
    (attempt / 'answer.md').write_text('Original scientific answer. [expert/map]\n')
    return attempt, root


def result_record(root, result_id='view_1', kind='interactive_view', files=None):
    files = files or {'data.nc': b'final declared data', 'preview.png': b'final PNG'}
    records, locations = [], {}
    for name, contents in files.items():
        relative = f'agents/expert/outputs/{result_id}/{name}'
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        records.append({'path': name, 'size': len(contents),
                        'sha256': hashlib.sha256(contents).hexdigest()})
        locations[name] = relative
    return {'result_ref': {'task_id': 'task_123456', 'result_id': result_id, 'version': 1},
            'kind': kind, 'title': f'Result {result_id}', 'files': records,
            'content': {'workspace_files': locations, 'data_file': 'data.nc',
                        'preview_file': 'preview.png', 'result_key': 'expert/map'}}


def write_current_index(attempt, records):
    (attempt / 'outputs.json').write_text(json.dumps({
        'outputs': [], 'delivery_manifests': [], 'task_results': records,
    }))


def collected_attempt(attempt):
    collection = collect_run(attempt.parents[1])
    summary = json.loads((collection / 'summary.json').read_text())[0]
    target = (collection / summary['review']).parent
    return target, summary


def test_current_results_export_six_views_and_do_not_scan_intermediates(tmp_path):
    attempt, root = current_attempt(tmp_path)
    records = [result_record(root, f'view_{i}') for i in range(6)]
    records.append(records[0])  # A repeated identity does not create another figure.
    write_current_index(attempt, records)
    scratch = root / 'agents/expert/outputs/intermediate.nc'
    scratch.write_bytes(b'not published')
    answer = (attempt / 'answer.md').read_bytes()
    target, summary = collected_attempt(attempt)
    assert summary['png_count'] == summary['accepted_outputs'] == summary['registered_outputs'] == 6
    assert summary['collection_status'] == 'complete'
    assert (target / 'answer.md').read_bytes() == answer
    assert len(list((target / 'delivery').rglob('*.nc'))) == 6
    assert not list(target.rglob('intermediate.nc'))
    review = (target / 'review.md').read_text()
    assert '![Figure](delivery/view_0/v0001/preview.png)' in review
    manifest = json.loads((target / 'collection_manifest.json').read_text())
    assert manifest['source'] == 'task_results' and manifest['recomputed'] is False
    assert summary['notebook_kind'] == 'missing'  # Do not invent an analysis notebook.


def test_current_results_use_immutable_store_and_collect_reports_and_tables(tmp_path):
    attempt, root = current_attempt(tmp_path)
    record = result_record(root, 'table_1', kind='table', files={'table.csv': b'x,y\n1,2\n'})
    location = root / record['content']['workspace_files']['table.csv']
    immutable = root / 'results/table_1/v0001/table.csv'
    immutable.parent.mkdir(parents=True)
    location.rename(immutable)
    record['content']['workspace_files'] = {}
    write_current_index(attempt, [record])
    for agent in ['expert', 'coordinator']:
        p = root / f'agents/{agent}/report.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'{agent} report')
    target, summary = collected_attempt(attempt)
    assert summary['accepted_outputs'] == 1 and summary['png_count'] == 0
    assert (target / 'delivery/table_1/v0001/table.csv').read_bytes() == b'x,y\n1,2\n'
    assert (target / 'reports/coordinator/report.md').read_text() == 'coordinator report'
    assert 'delivery/table_1/v0001/table.csv' in (target / 'review.md').read_text()


@pytest.mark.parametrize('failure', ['checksum', 'size', 'missing', 'escape', 'symlink', 'foreign_task'])
def test_current_result_integrity_failure_is_not_runtime_failure(tmp_path, failure):
    attempt, root = current_attempt(tmp_path)
    record = result_record(root)
    file = root / record['content']['workspace_files']['data.nc']
    if failure == 'checksum':
        record['files'][0]['sha256'] = '0' * 64
    elif failure == 'size':
        record['files'][0]['size'] += 1
    elif failure == 'missing':
        file.unlink()
    elif failure == 'escape':
        record['content']['workspace_files']['data.nc'] = '../outside.nc'
    elif failure == 'symlink':
        other = root / 'other.nc'
        file.rename(other)
        file.symlink_to(other)
    else:
        record['result_ref']['task_id'] = 'task_other'
    write_current_index(attempt, [record])
    target, summary = collected_attempt(attempt)
    assert summary['runtime_status'] == 'completed'
    assert summary['collection_status'] == 'partial'
    assert summary['collection_errors'] and summary['accepted_outputs'] == 0
    assert not list(target.rglob('data.nc'))  # Validate the entire result before copying.


def test_current_empty_index_does_not_resurrect_old_receipts(tmp_path):
    attempt, _ = current_attempt(tmp_path)
    write_current_index(attempt, [])
    old = attempt / 'delivery_manifest.json'
    old.write_text('{"outputs": [{"files": []}]}')
    _, summary = collected_attempt(attempt)
    assert summary['accepted_outputs'] == 0 and not summary['collection_errors']


def test_missing_preview_is_explicit_and_data_is_still_preserved(tmp_path):
    attempt, root = current_attempt(tmp_path)
    record = result_record(root, files={'data.nc': b'valid data'})
    write_current_index(attempt, [record])
    target, summary = collected_attempt(attempt)
    assert summary['accepted_outputs'] == 1 and summary['png_count'] == 0
    assert summary['collection_status'] == 'partial'
    assert 'no collected preview' in summary['collection_errors'][0]
    assert (target / 'delivery/view_1/v0001/data.nc').exists()


def test_execution_record_preserves_failed_cells_without_claiming_reproducibility(tmp_path):
    attempt, root = current_attempt(tmp_path)
    write_current_index(attempt, [result_record(root)])
    notebook = root / 'agents/expert/.runtime/executions/codeexec_1/code/analysis.ipynb'
    notebook.parent.mkdir(parents=True)
    original = {'cell_type': 'code', 'id': 'shared-id', 'metadata': {},
                'source': ['raise ValueError("recorded failure")'], 'execution_count': 1,
                'outputs': [{'output_type': 'error', 'ename': 'ValueError',
                             'evalue': 'recorded failure', 'traceback': []}]}
    notebook.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [original]}))
    target, summary = collected_attempt(attempt)
    assert summary['notebook_kind'] == 'execution_record'
    saved = json.loads((target / 'execution_record.ipynb').read_text())
    code = next(c for c in saved['cells'] if c['cell_type'] == 'code')
    assert code['source'] == original['source'] and code['outputs'] == original['outputs']
    assert saved['metadata']['oceanx_collection']['reexecuted'] is False
    assert 'NOT a clean' in ''.join(saved['cells'][0]['source'])
    assert not (target / 'analysis.ipynb').exists()
    assert notebook.read_text() == json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [original]})


def test_corrupt_index_reports_gap_instead_of_silent_zero_figures(tmp_path):
    attempt, _ = current_attempt(tmp_path)
    (attempt / 'outputs.json').write_text('{broken')
    _, summary = collected_attempt(attempt)
    assert summary['collection_status'] == 'partial' and summary['collection_errors']


def test_current_paths_in_review_are_portable_and_original_answer_unchanged(tmp_path):
    attempt, root = current_attempt(tmp_path)
    record = result_record(root)
    write_current_index(attempt, [record])
    preview = root / record['content']['workspace_files']['preview.png']
    text = f'Result [expert/map] and ![Original]({preview.resolve()})'
    (attempt / 'answer.md').write_text(text)
    target, _ = collected_attempt(attempt)
    assert (target / 'answer.md').read_text() == text
    review = (target / 'review.md').read_text()
    assert str(preview.resolve()) not in review
    assert '[Result view_1](delivery/view_1/v0001/preview.png)' in review


def test_result_named_result_json_does_not_overwrite_collection_metadata(tmp_path):
    attempt, root = current_attempt(tmp_path)
    record = result_record(root, 'file_1', kind='file', files={'result.json': b'{"scientific": 1}'})
    write_current_index(attempt, [record])
    target, summary = collected_attempt(attempt)
    assert summary['collection_status'] == 'complete'
    assert (target / 'delivery/file_1/v0001/result.json').read_bytes() == b'{"scientific": 1}'
    assert json.loads((target / 'records/file_1/v0001.json').read_text()) == record
