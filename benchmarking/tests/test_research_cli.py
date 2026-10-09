"""The benchmark's learning step asks for the repeated code of one question for a tool."""
import os

import research_cli


def test_the_learning_step_sets_one_question_unless_the_owner_set_another(monkeypatch):
    from oceanx.research import cli
    started = []
    monkeypatch.setattr(research_cli, "install_oceanx_models", lambda: started.append("models"))
    monkeypatch.setattr(cli, "research_app", lambda **options: started.append(options["prog_name"]))
    environment = {key: value for key, value in os.environ.items() if key != "OCEANX_TOOL_MIN_SUPPORT"}
    monkeypatch.setattr(os, "environ", environment)
    research_cli.main()
    assert environment["OCEANX_TOOL_MIN_SUPPORT"] == "1" and started == ["models", "research_cli.py"]
    environment["OCEANX_TOOL_MIN_SUPPORT"] = "3"
    research_cli.main()
    assert environment["OCEANX_TOOL_MIN_SUPPORT"] == "3"
