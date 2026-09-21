"""AgentScope adapter whose business action is one Wren HTTP call."""

from agentscope.agent import Agent
from agentscope.middleware import MiddlewareBase
from agentscope.pipeline import PipelineProtocol

from .query_workflow import QueryWorkflow


class QueryBinding(MiddlewareBase):
    def __init__(
        self,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        publisher,
        wren,
        checkpoint,
        audit,
    ) -> None:
        self.user_id = user_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.publisher = publisher
        self.wren = wren
        self.checkpoint = checkpoint
        self.audit = audit


class QueryAgent(Agent):
    def __init__(self, *args, middlewares=None, **kwargs):
        binding = next(m for m in middlewares or [] if isinstance(m, QueryBinding))
        super().__init__(*args, middlewares=middlewares, **kwargs)
        self.workflow: PipelineProtocol = QueryWorkflow(self, binding)

    async def reply_stream(self, inputs=None, structured_schema=None, yield_final_msg=False):
        async for event in self.workflow.reply_stream(
            inputs,
            structured_schema=structured_schema,
            yield_final_msg=yield_final_msg,
        ):
            yield event
