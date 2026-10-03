"""The Finch sandbox command, checked as arguments: no namespaces and no Bubblewrap needed."""
from pathlib import Path

from finch_sandbox import sandbox_command


def spec_for(executable, runtime_roots, workspace):
    return {"workspace": str(workspace), "mounts": [],
            "kernel": {"executable": str(executable), "runtime_roots": [str(root) for root in runtime_roots]},
            "bwrap": "/usr/bin/bwrap", "prlimit": "/usr/bin/prlimit", "taskset": "/usr/bin/taskset",
            "memory_bytes": 8 * 1024**3, "cpus": 1, "cpu_ids": [0], "execution_timeout": 30}


def read_only_mounts(args):
    """(source on the host, path inside the sandbox) of every read-only mount."""
    return [(Path(args[i + 1]), Path(args[i + 2])) for i, arg in enumerate(args) if arg == "--ro-bind"]


def test_the_interpreter_is_visible_at_the_path_it_is_launched_by_when_its_directory_is_an_alias(tmp_path):
    # The benchmark server: /home/<user> is an alias of /import/home2/<user>. pytest and the kernel check
    # report the interpreter as /home/<user>/..., while only the resolved folder was mounted, so
    # taskset failed with "failed to execute .../bin/python: No such file or directory".
    prefix = tmp_path / "import-home2" / "user" / "envs" / "bench"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "python").write_text("")
    (tmp_path / "home").symlink_to(tmp_path / "import-home2")
    launched_by = tmp_path / "home" / "user" / "envs" / "bench" / "bin" / "python"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = spec_for(launched_by, [launched_by.parents[1]], workspace)

    args = sandbox_command(spec, [str(launched_by), "-c", "pass"])

    visible_at = [inside for _host, inside in read_only_mounts(args) if launched_by.is_relative_to(inside)]
    assert visible_at, "the interpreter's own path does not exist inside the sandbox"
    assert {host for host, inside in read_only_mounts(args) if inside in visible_at} == {prefix.resolve()}
    assert str(launched_by) in args  # the command is unchanged: the same path now exists inside


def test_a_runtime_folder_reached_by_its_real_path_is_mounted_once(tmp_path):
    prefix = tmp_path / "envs" / "bench"
    (prefix / "bin").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = spec_for(prefix / "bin" / "python", [prefix], workspace)

    args = sandbox_command(spec, [str(prefix / "bin" / "python"), "-c", "pass"])

    assert [inside for _host, inside in read_only_mounts(args)].count(prefix.resolve()) == 1


def test_an_alias_named_twice_is_mounted_once(tmp_path):
    prefix = tmp_path / "import-home2" / "user" / "envs" / "bench"
    (prefix / "bin").mkdir(parents=True)
    (tmp_path / "home").symlink_to(tmp_path / "import-home2")
    alias = tmp_path / "home" / "user" / "envs" / "bench"  # sys.prefix and sys.base_prefix are one folder
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = spec_for(alias / "bin" / "python", [alias, alias], workspace)

    args = sandbox_command(spec, [str(alias / "bin" / "python"), "-c", "pass"])

    assert [inside for _host, inside in read_only_mounts(args)].count(alias) == 1
