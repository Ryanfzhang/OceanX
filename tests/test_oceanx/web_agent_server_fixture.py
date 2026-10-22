"""Native web server with deterministic agents and one synthetic scientific figure."""
from tests.test_oceanx.agent_server_fixture import FixtureModel, install


def install_web_fixture():
    install()
    from oceanx import deep_runtime

    class WebFixtureModel(FixtureModel):
        def _single_agent(self, messages, call):
            # Exercise the same automatic handoff the browser requests.
            return call("hand_to_research_team", {"reason": "Synthetic figure needs the research team.", "progress": ""})

        def _generate(self, messages, **kwargs):
            result = super()._generate(messages, **kwargs)
            for generation in result.generations:
                for call in generation.message.tool_calls:
                    if call["name"] == "ocean_expert_run_code" and "CREATED" in call["args"].get("code", ""):
                        call["args"]["code"] += (
                            "from oceanx.scientific_view import ScientificFigure\n"
                            "fig = ScientificFigure(plot_kind='timeseries', title='Synthetic web figure')\n"
                            "fig.panel(x=[1,2,3], y=[1,4,2], x_label='Day', y_label='Synthetic').line()\n"
                            "fig.save('web-check.nc')\n"
                        )
            return result

    deep_runtime.create_chat_model = lambda *args, **kwargs: WebFixtureModel(responses=[])


if __name__ == "__main__":
    install_web_fixture()
    from oceanx.web.backend import main
    main()
