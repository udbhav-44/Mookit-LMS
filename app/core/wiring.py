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
from app.files.render import render_pdf_to_images
from app.gen.announcement_generator import OpenAIAnnouncementGenerator
from app.gen.quiz.blueprint import LLMComprehender, VisionComprehender
from app.gen.quiz.generator import OpenAIQuestionGenerator
from app.gen.quiz.pipeline import QuizPipeline
from app.gen.quiz.solve_verify import LLMSolveCritique
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

    # Blueprint-first quiz pipeline (comprehend → plan → multi-span generate) when enabled; otherwise
    # the legacy one-span-per-question path. Comprehension uses a dedicated (long-context) model.
    if settings.quiz_blueprint_enabled:
        blueprint_provider = OpenAIProvider(client, default_model=settings.openai.blueprint_model)
        comprehender = LLMComprehender(
            blueprint_provider, temperature=settings.openai.comprehend_temperature
        )
        # Independent solve-critique (re-derive each answer from evidence) flags reasoning/key errors
        # the deterministic numeric check can't catch. Deterministic temperature.
        critique = None
        if settings.quiz_solve_verify_enabled:
            critique = LLMSolveCritique(provider, temperature=settings.openai.verify_temperature)

        vision_kwargs: dict = {}
        if settings.quiz_vision_enabled:
            # Vision reads equations/figures from rendered page images; grounding still uses the text.
            vision_kwargs = {
                "vision_comprehender": VisionComprehender(
                    blueprint_provider, temperature=settings.openai.comprehend_temperature
                ),
                "fetch_source": _make_fetch_source(session_factory),
                "render_pages": lambda data: render_pdf_to_images(
                    data, max_pages=settings.limits.vision_max_pages
                ),
            }
        pipeline = QuizPipeline(
            retrieve=rag_store.retrieve,
            generator=generator,
            comprehender=comprehender,
            fetch_all=rag_store.fetch_all_chunks,
            critique=critique,
            **vision_kwargs,
        )
    else:
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


def _make_fetch_source(session_factory):
    """Build a fetch_source seam: doc_id → original uploaded file bytes (for vision page rendering).

    Tenant-scoped via FileMeta; returns None if the document is unknown or its file is unreadable."""
    from pathlib import Path

    from sqlalchemy import select

    from app.store.db import FileMeta

    async def fetch_source(ctx: RequestContext, doc_artifact_id: str) -> bytes | None:
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(FileMeta).where(
                        FileMeta.id == doc_artifact_id,
                        FileMeta.tenant_key == ctx.tenant_key,
                    )
                )
            ).scalar_one_or_none()
        if row is None or not getattr(row, "storage_path", None):
            return None
        try:
            return Path(row.storage_path).read_bytes()
        except OSError:
            return None

    return fetch_source
