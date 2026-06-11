#!/usr/bin/env python
"""Live preview of Phase 1 comprehension: a document → grounded assessment Blueprint.

Run it against a real source file to judge comprehension quality before investing in the pipeline
rewrite. Requires an OpenAI key (env OPENAI_API_KEY or OPENAI__API_KEY).

    OPENAI_API_KEY=sk-... python scripts/preview_blueprint.py tests/fixtures/sample.pdf.txt

Optional flags:
    --model gpt-4o        override the comprehension model (default: settings.openai.blueprint_model)
    --reading undergraduate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.gen.quiz.blueprint import LLMComprehender, ground_blueprint
from app.gen.quiz.params import QuizParams
from app.gen.quiz.source_router import estimate_tokens, route
from app.llm.openai import OpenAIProvider


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="path to a source file (.txt for text mode, .pdf for --vision)")
    ap.add_argument("--model", default=settings.openai.blueprint_model)
    ap.add_argument("--reading", default="undergraduate")
    ap.add_argument("--vision", action="store_true", help="render PDF pages and comprehend via vision")
    args = ap.parse_args()

    key = settings.openai.api_key.get_secret_value()
    if key in ("", "sk-placeholder"):
        print("ERROR: set OPENAI_API_KEY (or OPENAI__API_KEY) to run the live preview.", file=sys.stderr)
        return 2

    provider = OpenAIProvider(AsyncOpenAI(api_key=key), default_model=args.model)
    params = QuizParams(reading_level=args.reading)

    if args.vision:
        from app.files.render import render_pdf_to_images
        from app.gen.quiz.blueprint import VisionComprehender, ground_blueprint_multi

        data = Path(args.path).read_bytes()
        images = render_pdf_to_images(data, max_pages=settings.limits.vision_max_pages)
        # Extract text (pdfminer) purely for grounding the vision-read quotes.
        from pdfminer.high_level import extract_text
        text = extract_text(args.path)
        print(f"vision · {len(images)} page image(s) · model: {args.model}\n")
        bp = await VisionComprehender(provider, temperature=settings.openai.comprehend_temperature)(
            images=images, params=params
        )
        grounded = ground_blueprint_multi(bp, sources={"preview": text}, on_unmatched="flag")
        print_blueprint(grounded)
        return 0

    text = Path(args.path).read_text(encoding="utf-8")
    mode = route(total_chars=len(text), n_docs=1, context_token_budget=settings.openai.context_token_budget)
    print(f"~{estimate_tokens(text)} tokens · source mode: {mode.value} · model: {args.model}\n")

    comprehender = LLMComprehender(provider, temperature=settings.openai.comprehend_temperature)
    bp = await comprehender(sections=[text], params=params)
    grounded = ground_blueprint(bp, source_text=text, source_doc_id="preview")
    print_blueprint(grounded)
    return 0


def print_blueprint(grounded) -> None:  # noqa: ANN001 — GroundedBlueprint
    print(f"OBJECTIVES ({len(grounded.objectives)}):")
    for o in grounded.objectives:
        print(f"  [{o.bloom}] {o.statement}  → concepts {o.concept_ids}")
    print(f"\nCONCEPTS ({len(grounded.concepts)}):")
    for gc in grounded.concepts:
        c = gc.concept
        print(f"  {c.id} · {c.name}  [{c.kind}]  (bloom: {', '.join(c.suggested_bloom)})")
        print(f"      {c.summary}")
        if c.formulas:
            print(f"      formulas: {c.formulas}")
        if c.common_misconceptions:
            print(f"      misconceptions: {c.common_misconceptions}")
        print(f"      cite: \"{gc.citation.quote[:90]}...\" @ {gc.citation.locator}")
    print(f"\nQUANTITATIVE RATIO: {grounded.quantitative_ratio}")
    print("SUGGESTED DISTRIBUTION:")
    for d in grounded.suggested_distribution:
        print(f"  {d.bloom}: {d.count}")
    if grounded.warnings:
        print("\nWARNINGS (dropped/flagged):")
        for w in grounded.warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
