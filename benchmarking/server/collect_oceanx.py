"""Collect benchmark attempts into a portable review directory without calling models."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path, PurePosixPath


def safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in value:
        raise ValueError("Unsafe recorded output path")
    return Path(*path.parts)


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(root: Path, relative: str, record: dict) -> Path:
    """Validate a recorded benchmark file without importing a runtime adapter."""
    original = root / safe_relative(relative)
    if any(part.is_symlink() for part in (original, *original.parents)):
        raise ValueError("Recorded output is a symlink")
    candidate = original.resolve(strict=True)
    if root.resolve() not in candidate.parents or not candidate.is_file():
        raise ValueError("Recorded output escapes its benchmark directory")
    size = record.get('size', record.get('bytes'))
    if size is not None and candidate.stat().st_size != size:
        raise ValueError("Recorded output size does not match")
    digest = digest_file(candidate)
    if record.get("sha256") and record["sha256"] != digest:
        raise ValueError("Recorded output checksum does not match")
    return candidate


def task_root(attempt: Path, task_id: str) -> Path:
    """Resolve the task by its saved identity, not its mutable display title."""
    roots = []
    for manifest in (attempt / 'workspace' / 'OceanX Tasks').glob('*/task-manifest.json'):
        checked_file(attempt, manifest.relative_to(attempt).as_posix(), {})
        if json.loads(manifest.read_text()).get('task', {}).get('task_id') == task_id:
            roots.append(manifest.parent)
    if len(roots) != 1:
        raise ValueError("Expected one workspace for the recorded task identity")
    return roots[0]


def collect_task_results(attempt: Path, target: Path, records: list, task_id: str | None,
                         errors: list[str]) -> tuple[list[dict], dict[str, str]]:
    """Copy only registered files. No filesystem discovery of scientific results."""
    collected, replacements, seen = [], {}, set()
    roots = {}
    for record in records:
        label = 'task result'
        try:
            ref = record['result_ref']
            owner, result_id, version = ref['task_id'], ref['result_id'], ref['version']
            label = str(result_id)
            if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]+', v)
                       for v in (owner, result_id)):
                raise ValueError("Invalid task result identity")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("Invalid task result version")
            if task_id is not None and owner != task_id:
                raise ValueError("Result belongs to another task")
            identity = (owner, result_id, version)
            if identity in seen:
                continue
            seen.add(identity)
            if owner not in roots:
                roots[owner] = task_root(attempt, owner)
            root = roots[owner]
            content = record.get('content') or {}
            locations = content.get('workspace_files') or {}
            files = record['files']
            if not isinstance(files, list) or not isinstance(locations, dict):
                raise ValueError("Invalid task result files")
            validated = {}
            for file in files:
                name = safe_relative(file['path']).as_posix()
                if name in validated:
                    raise ValueError("Duplicate result file")
                if name in locations:
                    source = checked_file(root, locations[name], file)
                else:
                    source = checked_file(root, f'results/{result_id}/v{version:04d}/{name}', file)
                validated[name] = source
            if record['kind'] == 'interactive_view':
                data_name = content.get('data_file') or content.get('dataset_file')
                if data_name not in validated:
                    raise ValueError("Interactive result has no registered data file")
            bundle = target / 'delivery' / result_id / f'v{version:04d}'
            bundle.mkdir(parents=True)
            record_path = target / 'records' / result_id / f'v{version:04d}.json'
            record_path.parent.mkdir(parents=True)
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
            copied = []
            for name, source in validated.items():
                destination = bundle / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                relative = destination.relative_to(target).as_posix()
                replacements[str(source)] = relative
                copied.append(relative)
            preview_name = content.get('preview_file')
            preview = ((bundle / preview_name).relative_to(target).as_posix()
                       if preview_name in validated else None)
            if record['kind'] == 'interactive_view' and preview is None:
                errors.append(f'{label}: registered view has no collected preview')
            entry = {'result_ref': ref, 'kind': record['kind'], 'title': record['title'],
                     'files': copied, 'preview': preview,
                     'metadata': record_path.relative_to(target).as_posix()}
            collected.append(entry)
            destination_link = preview or (copied[0] if copied else entry['metadata'])
            keys = {f'{owner}/{result_id}', f'{owner}/{result_id}@v{version}'}
            if isinstance(content.get('result_key'), str):
                keys.add(content['result_key'])
            title = str(record['title']).replace('[', '\\[').replace(']', '\\]')
            for key in keys:
                replacements[f'[{key}]'] = f'[{title}]({destination_link})'
                replacements[f'[[result:{key}]]'] = f'[{title}]({destination_link})'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{label}: {exc}')
    return collected, replacements


def collect_analysis_records(attempt: Path, target: Path, task_id: str | None,
                             errors: list[str]) -> tuple[list[str], str]:
    """Preserve authored reports/code and group saved notebook cells without running them."""
    if task_id is None:
        return [], 'missing'
    try:
        root = task_root(attempt, task_id)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f'analysis records: {exc}')
        return [], 'missing'
    documents = []
    cells = [{'cell_type': 'markdown', 'metadata': {}, 'source': [
        '# Saved execution records\n\n',
        'This file is assembled offline from recorded OceanX code executions. '
        'It is NOT a clean, end-to-end reproducible analysis notebook. Cells may contain '
        'failed attempts, depend on an existing kernel, use original server paths, or '
        'overwrite earlier results. Executions are grouped by agent and ordered by their '
        'saved file modification times; this is not a cross-agent causal ordering. '
        'No code was executed and no new scientific result was generated during collection.\n',
    ]}]
    notebook_count = 0
    agents = root / 'agents'
    for agent in sorted(agents.iterdir()) if agents.is_dir() else []:
        if not agent.is_dir() or agent.is_symlink():
            continue
        for name in ('report.md', 'analysis.py'):
            source = agent / name
            if not source.exists():
                continue
            try:
                source = checked_file(root, source.relative_to(root).as_posix(), {})
                destination = target / 'reports' / agent.name / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                documents.append(destination.relative_to(target).as_posix())
            except (OSError, ValueError) as exc:
                errors.append(f'{agent.name}/{name}: {exc}')
        executions = list((agent / '.runtime' / 'executions').glob('*/code/analysis.ipynb'))
        executions.sort(key=lambda p: (p.lstat().st_mtime_ns, str(p)))
        for source in executions:
            try:
                source = checked_file(root, source.relative_to(root).as_posix(), {})
                notebook = json.loads(source.read_text())
                if notebook.get('nbformat') != 4 or not isinstance(notebook.get('cells'), list):
                    raise ValueError('Invalid saved notebook')
                cells.append({'cell_type': 'markdown', 'metadata': {}, 'source': [
                    f'## {agent.name} / {source.parents[1].name}\n\n',
                    'Original saved cells follow; they have not been repaired or rerun.\n',
                ]})
                for cell in notebook['cells']:
                    cell = dict(cell)
                    cell.pop('id', None)  # Avoid duplicate IDs across execution notebooks.
                    cells.append(cell)
                notebook_count += 1
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f'{agent.name}/{source.parent.parent.name}: {exc}')
    if notebook_count:
        path = target / 'execution_record.ipynb'
        path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 4,
            'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                         'oceanx_collection': {'kind': 'execution_record', 'source_notebooks': notebook_count,
                                               'reexecuted': False}},
            'cells': cells}, ensure_ascii=False, indent=2) + '\n')
        documents.append(path.name)
        return documents, 'execution_record'
    return documents, 'missing'


SCRATCH_PRUNE_MIN_BYTES = 10_000_000


def _scratch_cleanup(attempt: Path, target: Path, task_id: str | None, *, ready: bool) -> dict:
    """Delete the large intermediate arrays of a complete, validated collection; keep everything else.

    A file over 10 MB is an array its script can rebuild from the frozen inputs; in the E10 run those
    files were 99.6% of the 5.4 GB. The scripts, tables and notes beside them stay, because reports cite
    them and a recorded command only calls a script by name. The record lists every file removed.
    If the final answer or a report cites a scratch folder by its absolute path, nothing is removed.
    """
    prior = attempt / 'scratch_cleanup.json'
    carried = []
    if prior.is_file() and not prior.is_symlink():
        try:
            existing = json.loads(prior.read_text(encoding='utf-8'))
            if existing.get('status') == 'cleaned':
                (target / 'scratch_cleanup.json').write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                return existing
            if existing.get('status') == 'partial':
                carried = list(existing.get('files') or [])  # this collection finishes the job
        except (OSError, ValueError, TypeError):
            pass
    record = {'schema_version': 2, 'status': 'retained', 'min_bytes': SCRATCH_PRUNE_MIN_BYTES,
              'file_count': 0, 'bytes_released': 0}
    if not ready:
        record['reason'] = 'collection is incomplete'
    elif task_id is None:
        record['reason'] = 'task identity is unavailable'
    else:
        try:
            root = task_root(attempt, task_id)
            scratches = sorted(
                path for path in (root / 'agents').glob('*/scratch')
                if path.is_dir() and not path.is_symlink()
            )
            texts = []
            reports = sorted((root / 'agents').rglob('report.md'))
            for path in [attempt / 'answer.md', *reports]:
                if path.is_file() and not path.is_symlink():
                    texts.append(path.read_text(encoding='utf-8', errors='replace'))
            references = [str(path) for path in scratches if any(str(path) in text for text in texts)]
            if references:
                record['reason'] = 'final text references scratch: ' + ', '.join(references)
            else:
                deleted, kept = list(carried), 0
                try:
                    for scratch in scratches:
                        for directory, subfolders, names in os.walk(scratch, followlinks=False):
                            subfolders.sort()
                            for name in sorted(names):
                                path = Path(directory) / name
                                if path.is_symlink() or not path.is_file():
                                    continue
                                size = path.stat().st_size
                                if size <= SCRATCH_PRUNE_MIN_BYTES:
                                    kept += 1
                                    continue
                                path.unlink()
                                deleted.append({'path': path.relative_to(root).as_posix(), 'bytes': size})
                    record['status'] = 'cleaned'
                finally:  # what was removed is recorded even when a later removal fails
                    record.update(file_count=len(deleted), bytes_released=sum(i['bytes'] for i in deleted),
                                  kept_file_count=kept, files=deleted)
        except (OSError, ValueError, TypeError) as exc:
            record['reason'] = f'cleanup could not be completed: {exc}'
            if record['file_count']:
                record['status'] = 'partial'
    content = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
    (target / 'scratch_cleanup.json').write_text(content, encoding='utf-8')
    (attempt / 'scratch_cleanup.json').write_text(content, encoding='utf-8')
    return record


def collect_run(run: Path, destination: Path | None = None) -> Path:
    run = run.resolve()
    if not run.is_dir():
        raise ValueError(f"Run directory does not exist: {run}")
    destination = destination or run / "collected" / f"collection-{time.time_ns()}"
    destination = destination.resolve()
    attempts = sorted(run.glob("*/attempt-*/result.json"))
    if not attempts:
        raise ValueError("No finished attempt records found; a running task can be collected later")
    destination.mkdir(parents=True, exist_ok=False)
    summary = []
    for result_path in attempts:
        attempt = result_path.parent
        relative = Path(attempt.parent.name) / attempt.name
        target = destination / relative
        target.mkdir(parents=True)
        result = json.loads(result_path.read_text())
        errors = []
        for name in ("result.json", "query.json", "submitted_prompt.txt", "answer.md", "analysis.ipynb", "outputs.json", "model_protocol.json", "delivery_protocol.json", "tree.json"):
            source = attempt / name
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, target / name)
        answer = target / "answer.md"
        has_answer = answer.is_file() and bool(answer.read_text().strip())
        figures = []
        accepted = 0
        entries, replacements, documents = [], {}, []
        notebook_kind = 'provided' if (target / 'analysis.ipynb').is_file() else 'missing'
        registered = None
        canonical = False
        output_path = attempt / 'outputs.json'
        if output_path.is_file():
            try:
                outputs = json.loads(checked_file(attempt, 'outputs.json', {}).read_text())
                canonical = 'task_results' in outputs
                if canonical:
                    records = outputs['task_results']
                    if not isinstance(records, list):
                        raise ValueError('task_results must be a list')
                    registered = len({json.dumps(r.get('result_ref'), sort_keys=True)
                                      for r in records if isinstance(r, dict)})
                    entries, replacements = collect_task_results(
                        attempt, target, records, result.get('task_id'), errors)
                    accepted = len(entries)
                    figures = [entry['preview'] for entry in entries if entry['preview']]
                    documents, execution_kind = collect_analysis_records(
                        attempt, target, result.get('task_id'), errors)
                    if notebook_kind != 'provided':
                        notebook_kind = execution_kind
            except (OSError, ValueError, KeyError, TypeError) as exc:
                canonical = True  # A corrupt current index is not a reason to expose stale receipts.
                errors.append(f'outputs.json: {exc}')
        manifests = [] if canonical else (
            [attempt / "delivery_manifest.json"] if (attempt / "delivery_manifest.json").exists()
            else sorted((attempt / "benchmark_delivery").glob("*/manifest.json")))
        for manifest_path in manifests:
            receipt = manifest_path.parent
            flat = manifest_path.name == "delivery_manifest.json"
            bundle = target if flat else target / "delivery" / receipt.name
            try:
                manifest = json.loads(manifest_path.read_text())
                entries = manifest["outputs"]
                records = [record for entry in entries for record in entry["files"]]
                records += [entry["preview"] for entry in entries if entry.get("preview")]
                # Validate the complete receipt before copying any of its artifacts.
                for record in records:
                    checked_file(receipt, record["path"], record)
                renderer = manifest.get("renderer")
                if renderer:
                    checked_file(receipt, renderer["path"], {
                        **renderer, "bytes": (receipt / renderer["path"]).stat().st_size,
                    })
                bundle.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(manifest_path, bundle / manifest_path.name)
                for record in records:
                    source = checked_file(receipt, record["path"], record)
                    output = bundle / record["path"]
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, output)
                if renderer:
                    shutil.copyfile(receipt / renderer["path"], bundle / renderer["path"])
                accepted += len(entries)
                for entry in entries:
                    if entry.get("preview"):
                        figure = (bundle / entry["preview"]["path"]).relative_to(target).as_posix()
                        figures.append(figure)
                        replacements[str(receipt / entry['preview']['path'])] = figure
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"{receipt.name}: {exc}")
        # Preserve the original answer byte-for-byte; the review copy gets portable PNG links.
        review = answer.read_text() if has_answer else "No final research answer was returned.\n"
        for original, replacement in sorted(replacements.items(), key=lambda pair: -len(pair[0])):
            review = review.replace(original, replacement)
        review += "\n\n## Collected figures\n\n"
        if canonical:
            review += '\n\n'.join(
                f"### {entry['title']}\n\n"
                + (f"![Figure]({entry['preview']})\n\n" if entry['preview'] else '')
                + '\n'.join(f'- [{Path(path).name}]({path})' for path in entry['files'])
                for entry in entries)
        else:
            review += "\n\n".join(f"![Figure {i}]({path})" for i, path in enumerate(figures, 1))
        if documents or notebook_kind == 'provided':
            review += '\n\n## Reports and saved code\n\n'
            if notebook_kind == 'provided':
                documents.insert(0, 'analysis.ipynb')
            review += '\n'.join(f'- [{path}]({path})' for path in documents)
        if notebook_kind == 'execution_record':
            review += ('\n\n**Notebook scope:** execution_record.ipynb preserves saved cells, '
                       'including failed attempts. It has not been rerun and is not a clean '
                       'end-to-end analysis notebook.\n')
        elif notebook_kind == 'missing':
            review += '\n\n**Notebook scope:** no notebook was available for collection.\n'
        delivery_status = 'complete' if has_answer and not errors else 'partial'
        if errors:
            review += '\n\n## Collection issues\n\n' + '\n'.join(f'- {error}' for error in errors)
        (target / "review.md").write_text(review, encoding="utf-8")
        scratch_cleanup = _scratch_cleanup(
            attempt, target, result.get('task_id'),
            ready=result.get('status') == 'completed' and has_answer and not errors,
        )
        delivery = {'schema_version': 1, 'source': 'task_results' if canonical else 'legacy_receipts',
                    'runtime_status': result.get('status'), 'collection_status': delivery_status,
                    'has_final_answer': has_answer, 'registered_outputs': registered,
                    'accepted_outputs': accepted, 'png_count': len(figures),
                    'notebook_kind': notebook_kind, 'analysis_notebook_provided': notebook_kind == 'provided',
                    'results': entries if canonical else [], 'documents': documents,
                    'collection_errors': errors, 'scratch_cleanup': scratch_cleanup,
                    'recomputed': False}
        (target / 'collection_manifest.json').write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + '\n')
        summary.append({
            "id": result.get("id", attempt.parent.name), "attempt": attempt.name,
            "runtime_status": result.get("status"), "has_final_answer": has_answer,
            "accepted_outputs": accepted, "png_count": len(figures), "collection_errors": errors,
            'collection_status': delivery_status, 'registered_outputs': registered,
            'notebook_kind': notebook_kind,
            'scratch_cleanup': scratch_cleanup,
            "elapsed_seconds": result.get("elapsed_seconds"),
            "coordinator_usage": result.get("coordinator_usage"), "expert_usage": result.get("expert_usage"),
            "review": (relative / "review.md").as_posix(),
        })
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    index = "# OceanX benchmark collection\n\nAll attempts are retained; runtime completion is not scientific correctness.\n\n"
    for item in summary:
        index += (f"- [{item['id']} / {item['attempt']}]({item['review']}): "
                  f"{item['runtime_status']}; final answer={item['has_final_answer']}; "
                  f"collection={item['collection_status']}; PNG={item['png_count']}; "
                  f"notebook={item['notebook_kind']}; collection errors={len(item['collection_errors'])}\n")
    (destination / "index.md").write_text(index, encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New collection directory")
    args = parser.parse_args()
    print(collect_run(args.run, args.output))
