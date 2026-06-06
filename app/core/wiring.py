"""Wire the Dev B Orchestrator onto Dev A's platform resources.

Called from app.main lifespan to set app.state.orchestrator. Constructs the LLM provider, the full
tool registry (common + assessment + announcement + lecture), the quiz pipeline (RAG retrieve +
OpenAI generator), and a proposal sink backed by the DB ConfirmationGate.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from app.config import Settings
from app.contracts import ProposedAction, RequestContext
from app.core.confirmation import ConfirmationGate
from app.core.guardrails import make_openai_guardrail
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.gen.announcement_generator import OpenAIAnnouncementGenerator
from app.gen.quiz.generator import OpenAIQuestionGenerator
from app.gen.quiz.pipeline import QuizPipeline
from app.llm.openai import OpenAIProvider
from app.tools.announcement import DraftAnnouncementTool, SendAnnouncementTool
from app.tools.assessment import CreateQuizTool, EditQuizTool, PublishAssessmentTool
from app.tools.common import PermissionIntrospectTool, ResolveTaxonomyTool, WhoAmITool
from app.tools.echo import EchoTool
from app.tools.lecture import DraftLectureTool, PublishLectureTool
from app.tools.registry import ToolRegistry


def build_orchestrator(
    *,
    settings: Settings,
    mookit_client,
    session_store,
    artifact_registry,
    rag_store,
    session_factory,
    openai_client=None,
) -> Orchestrator:
    client = openai_client or AsyncOpenAI(api_key=settings.openai.api_key.get_secret_value())
    provider = OpenAIProvider(client, default_model=settings.openai.model)
    fast_provider = OpenAIProvider(client, default_model=settings.openai.fast_model)
    guardrail_hook = make_openai_guardrail(client)
    generator = OpenAIQuestionGenerator(provider, temperature=settings.openai.quiz_temperature)
    announcement_generator = OpenAIAnnouncementGenerator(fast_provider, temperature=0.7)
    pipeline = QuizPipeline(retrieve=rag_store.retrieve, generator=generator)

    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(WhoAmITool(mookit_client))
    registry.register(ResolveTaxonomyTool(mookit_client))
    registry.register(PermissionIntrospectTool())
    registry.register(CreateQuizTool(pipeline, artifact_registry))
    registry.register(EditQuizTool(pipeline, artifact_registry))
    registry.register(PublishAssessmentTool(artifact_registry))
    registry.register(DraftAnnouncementTool(artifact_registry, generator=announcement_generator))
    registry.register(SendAnnouncementTool(artifact_registry))
    registry.register(DraftLectureTool(mookit_client, artifact_registry))
    registry.register(PublishLectureTool(artifact_registry))

    gate = ConfirmationGate(session_factory)

    async def proposal_sink(ctx: RequestContext, action: ProposedAction) -> tuple[str, str]:
        return await gate.propose(ctx, action)

    return Orchestrator(
        llm=provider,
        registry=registry,
        sessions=session_store,
        artifacts=artifact_registry,
        resolver=ReferenceResolver(artifact_registry),
        mookit=mookit_client,
        settings=settings,
        proposal_sink=proposal_sink,
        guardrail_hook=guardrail_hook,
    )
