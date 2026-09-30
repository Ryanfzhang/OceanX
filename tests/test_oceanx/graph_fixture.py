"""In-process unit-test harness only. The product always executes on Agent Server."""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from oceanx.deep_runtime import DeepAgentEngine, build_deep_agent_graph
from oceanx.storage import OceanPaths


async def build_deep_agent_engine(*, profile, tools, system_prompt, cwd, thread_id,
                                  max_turns, operation_id_factory, subagents=None, **kwargs):
    path = OceanPaths.for_project(cwd).root / "langgraph.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    context = AsyncSqliteSaver.from_conn_string(str(path))
    saver = await context.__aenter__()
    await saver.setup()
    graph = await build_deep_agent_graph(profile=profile, tools=tools, system_prompt=system_prompt,
        cwd=cwd, operation_id_factory=operation_id_factory, subagents=subagents, checkpointer=saver)
    engine = DeepAgentEngine(
        graph=graph,
        thread_id=thread_id,
        operation_id_factory=operation_id_factory,
    )
    async def close():
        await context.__aexit__(None, None, None)
    return engine, close
