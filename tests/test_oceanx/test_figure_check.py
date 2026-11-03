"""Each figure an agent saves is checked for what its own look missed (figure_check.py): a smoothed curve
squashed under its raw series, a colour range far from its field, bars on a log axis, type too small to
read. Runs of 2026-11-03 delivered all four, their agents having read the rules that forbid them."""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from oceanx.expert_execution import _figure_check_notes
from oceanx.figure_check import problems


def _series(ax):
    days = np.arange(4000)
    noise = 40 * np.sin(days * 0.7) + 15 * np.cos(days * 0.13)
    smooth = 2 * np.sin(days / 600)
    ax.plot(days, noise, color="0.75", linewidth=0.5)
    ax.plot(days, smooth, color="black", linewidth=1.5)
    ax.text(0.02, 0.9, "(b)", transform=ax.transAxes)
    return smooth


def test_a_curve_squashed_under_its_raw_series_is_found_and_one_fitted_to_it_is_not():
    fig, ax = plt.subplots()
    _series(ax)
    (found,) = problems(fig)
    assert found.startswith("panel (b): the main curve spans") and "set the y limits from the main curve" in found
    ax.set_ylim(-2.4, 2.4)  # fitted to the main curve, the raw series running off
    assert problems(fig) == []
    plt.close(fig)


def test_a_colour_range_far_from_its_field_is_found():
    lon, lat = np.meshgrid(np.linspace(105, 122, 40), np.linspace(5, 23, 40))
    field = 3 * np.sin(lon / 3) * np.cos(lat / 4)  # about -3 to 3
    fig, (wide, narrow, fitted) = plt.subplots(1, 3)
    wide.contourf(lon, lat, field, levels=np.linspace(-20, 20, 9), cmap="RdBu_r", extend="both")
    narrow.pcolormesh(lon, lat, 10 * field, vmin=-5, vmax=5, cmap="RdBu_r")
    fig.colorbar(fitted.contourf(lon, lat, field, levels=np.linspace(-3, 3, 13), cmap="RdBu_r"), ax=fitted)
    found = problems(fig)
    assert len(found) == 2, found
    assert found[0].startswith("axes 1: the field spans") and "of its colour range -20 to 20" in found[0]
    assert found[1].startswith("axes 2: the field reaches") and "beyond its colour range -5 to 5" in found[1]
    plt.close(fig)


def test_bars_on_a_log_axis_and_type_too_small_are_found():
    fig, (log, linear) = plt.subplots(1, 2)
    log.barh(["cor", "adv", "pgf"], [7, -1, 4471])
    log.set_xscale("symlog", linthresh=20)
    linear.barh(["cor", "adv"], [7, -1])
    fig.text(0.1, 0.02, "residual = accel - (adv + cor) carries the rest", fontsize=5.6)
    found = problems(fig)
    assert any(item.startswith("axes 1: the bars are on a symlog axis") for item in found), found
    assert not any(item.startswith("axes 2") for item in found)
    assert any(item.startswith("text too small to read: 'residual = accel") and "5.6 pt" in item for item in found)
    plt.close(fig)


def test_a_figure_in_the_publication_style_gives_no_notes():
    fig, (series, field) = plt.subplots(2, 1)
    smooth = _series(series)
    series.set_ylim(smooth.min() * 1.1, smooth.max() * 1.1)
    series.twinx().plot(np.arange(4000), np.cos(np.arange(4000) / 300), color="tab:green")
    data = np.random.default_rng(0).normal(size=(30, 30))
    fig.colorbar(field.pcolormesh(data, cmap="RdBu_r", vmin=-4, vmax=4), ax=field)
    assert problems(fig) == []
    plt.close(fig)


def test_the_run_reports_the_last_check_of_each_delivered_figure(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    for name in ("fig2.pdf", "fig3.pdf", "_draft.png"):
        (outputs / name).write_bytes(b"%PDF")
    log = tmp_path / "figure-check.jsonl"
    log.write_text(json.dumps({"path": str(outputs / "old.pdf"), "problems": ["from an earlier run"]}) + "\n")
    offset = log.stat().st_size
    records = [
        {"path": str(outputs / "fig2.pdf"), "problems": ["panel (a): the main curve spans 8% of the y range"]},
        {"path": str(outputs / "fig3.pdf"), "problems": ["axes 1: the bars are on a symlog axis"]},
        {"path": str(outputs / "fig3.pdf"), "problems": []},  # fixed and saved again in the same run
        {"path": str(outputs / "_draft.png"), "problems": ["a draft"]},
        {"path": str(tmp_path / "scratch.png"), "problems": ["outside the outputs"]},
    ]
    with log.open("a") as stream:
        stream.write("".join(json.dumps(record) + "\n" for record in records) + '{"torn')
    assert _figure_check_notes(log, offset, outputs) == (
        "outputs/fig2.pdf: panel (a): the main curve spans 8% of the y range",)
    assert _figure_check_notes(tmp_path / "missing.jsonl", 0, outputs) == ()


def test_a_python_started_with_the_check_as_sitecustomize_checks_what_pyplot_saves(tmp_path):
    """pyplot copies its savefig from Figure.savefig and checks that name, so a wrapper without it stopped
    every import of pyplot."""
    import os
    import subprocess

    from oceanx.figure_check import LOG_ENV, sitecustomize
    (tmp_path / "check").mkdir()
    (tmp_path / "check" / "sitecustomize.py").write_text(sitecustomize(), encoding="utf-8")
    code = SQUASHED.replace('os.path.join(os.environ["OCEAN_OUTPUT_DIR"], "{name}")', repr(str(tmp_path / "fig")))
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "check"), LOG_ENV: str(tmp_path / "check.jsonl"),
           "MPLBACKEND": "Agg"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=tmp_path)
    (record,) = [json.loads(line) for line in (tmp_path / "check.jsonl").read_text().splitlines()]
    assert record["path"] == str(tmp_path / "fig.png")  # the suffix matplotlib adds
    assert record["problems"][0].startswith("panel (a): the main curve spans")
    started = subprocess.run([sys.executable, "-c", "import sys; print('matplotlib' in sys.modules)"],
                             check=True, env=env, capture_output=True, text=True)
    assert started.stdout.strip() == "False"  # code that draws nothing does not load matplotlib


SQUASHED = """
import os
import matplotlib.pyplot as plt
import numpy as np

days = np.arange(4000)
fig, ax = plt.subplots()
ax.plot(days, 40 * np.sin(days * 0.7), color="0.75", linewidth=0.5)
ax.plot(days, 2 * np.sin(days / 600), color="black", linewidth=1.5)
ax.text(0.02, 0.9, "(a)", transform=ax.transAxes)
fig.savefig(os.path.join(os.environ["OCEAN_OUTPUT_DIR"], "{name}"))
"""


@pytest.mark.asyncio
async def test_the_agents_python_checks_each_figure_it_saves(tmp_path: Path, monkeypatch):
    """Through the real sandbox: the kernel and a script started by a shell command load the check as their
    sitecustomize, and a figure fixed and saved again in the same run is reported no longer."""
    from oceanx.backend.host import OceanBackendHost
    from oceanx.sandbox import get_sandbox_execution_capabilities
    from tests.test_oceanx.test_research_library_router import _open_project

    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_check")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "figures"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        run = {"workspace_id": "ws_check", "task_id": task_id, "agent_thread_id": "single-agent-x",
               "server_run_id": "run"}
        service = host.expert_code_execution
        kernel = await service.run_python(**run, purpose="Draw", code=SQUASHED.replace("{name}", "fig2.pdf"))
        assert kernel.state == "succeeded", kernel.as_payload()
        assert any(note.startswith("outputs/fig2.pdf: panel (a): the main curve spans")
                   for note in kernel.figure_notes), kernel.figure_notes
        script = Path(kernel.work_root) / "scratch" / "fig.py"
        script.write_text(SQUASHED.replace("{name}", "fig4.png"), encoding="utf-8")
        shell = await service.run_shell(**run, command="python fig.py")
        assert shell.state == "succeeded", shell.as_payload()
        assert any(note.startswith("outputs/fig4.png: panel (a)") for note in shell.figure_notes), shell.figure_notes
        fixed = SQUASHED.replace("fig.savefig", "ax.set_ylim(-2.2, 2.2)\nfig.savefig").replace("{name}", "fig2.pdf")
        again = await service.run_python(**run, purpose="Fit the axis", code=SQUASHED.replace("{name}", "fig2.pdf")
                                         + fixed)
        assert again.state == "succeeded" and not any("fig2.pdf: panel" in note for note in again.figure_notes)
    finally:
        await host.close()
