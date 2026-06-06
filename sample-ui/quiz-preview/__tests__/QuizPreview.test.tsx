import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "../ConfirmDialog";
import QuizPreview from "../QuizPreview";
import type { AssessmentDraft, PreviewRender } from "../types";

const draft: AssessmentDraft = {
  id: "art_1",
  title: "Photosynthesis Quiz",
  version: 1,
  provenance: { ai_generated: true, edited_by_human: false, label: "AI-generated · edited by instructor", source_ids: ["doc-1"] },
  payload: {
    warnings: ["1 higher-order Bloom question(s) — review carefully"],
    questions: [
      {
        questionType: "mcq_single",
        questionText: "Where does photosynthesis occur?",
        bloom_level: "understand",
        score: 1,
        flags: [],
        citation: { source_id: "doc-1", locator: { page: 1 }, quote: "occurs in the chloroplast" },
        options: [
          { optionText: "Chloroplast", isCorrect: true },
          { optionText: "Nucleus", isCorrect: false, misconception: "confuses DNA site with energy site" },
        ],
      },
    ],
  },
};

describe("QuizPreview", () => {
  it("renders title, provenance badge, and warnings", () => {
    render(<QuizPreview draft={draft} onEdit={vi.fn()} onViewSource={vi.fn()} onPublish={vi.fn()} />);
    expect(screen.getByText("Photosynthesis Quiz")).toBeTruthy();
    expect(screen.getByText("AI-generated")).toBeTruthy();
    expect(screen.getByText(/higher-order Bloom/)).toBeTruthy();
  });

  it("dispatches delete op", () => {
    const onEdit = vi.fn();
    render(<QuizPreview draft={draft} onEdit={onEdit} onViewSource={vi.fn()} onPublish={vi.fn()} />);
    fireEvent.click(screen.getByText("Delete"));
    expect(onEdit).toHaveBeenCalledWith({ op: "remove", index: 0 });
  });

  it("view source opens the citation", () => {
    const onViewSource = vi.fn();
    render(<QuizPreview draft={draft} onEdit={vi.fn()} onViewSource={onViewSource} onPublish={vi.fn()} />);
    fireEvent.click(screen.getByText("View source"));
    expect(onViewSource).toHaveBeenCalledWith(draft.payload.questions[0]);
  });
});

describe("ConfirmDialog", () => {
  it("renders audience chip and diff", () => {
    const preview: PreviewRender = {
      title: "Publish lecture: Intro",
      summary_lines: ["Week 4"],
      audience: "142 students in CS101",
      diff: [{ field: "title", before: null, after: "Intro" }],
      warnings: [],
    };
    render(<ConfirmDialog preview={preview} onConfirm={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText(/142 students/)).toBeTruthy();
    expect(screen.getByText("title")).toBeTruthy();
  });
});
