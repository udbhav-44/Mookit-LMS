// Types mirroring the Dev B artifact payload + contracts (kept loose where the backend is flexible).

export type QuestionType =
  | "mcq_single"
  | "mcq_multi"
  | "true_false"
  | "fib"
  | "descriptive";

export type BloomLevel =
  | "remember"
  | "understand"
  | "apply"
  | "analyze"
  | "evaluate"
  | "create";

export interface Citation {
  source_id: string;
  locator: Record<string, unknown>;
  quote: string;
}

export interface Option {
  optionText: string;
  isCorrect: boolean;
  misconception?: string | null;
}

export interface Question {
  questionType: QuestionType;
  questionText: string;
  bloom_level: BloomLevel;
  score: number;
  citation: Citation;
  flags: string[];
  options?: Option[];
  trueFalseAnswer?: 0 | 1;
}

export interface Provenance {
  ai_generated: boolean;
  edited_by_human: boolean;
  label: string;
  source_ids: string[];
}

export interface AssessmentDraft {
  id: string;
  title: string;
  version: number;
  provenance: Provenance;
  payload: {
    questions: Question[];
    warnings: string[];
  };
}

// Edit operations dispatched back to the service (map to EditQuizTool ops).
export type EditOp =
  | { op: "remove"; index: number }
  | { op: "regenerate"; index: number }
  | { op: "replace_similar"; index: number }
  | { op: "change_type"; index: number; qtype: QuestionType }
  | { op: "set_difficulty"; difficulty: "easy" | "medium" | "hard" | "mixed" }
  | { op: "add"; qtype: QuestionType; delta: number }
  | { op: "edit_text"; index: number; questionText: string }
  | { op: "flag"; index: number; reason: string };

// PreviewRender (Contract 3) shown in the confirm dialog.
export interface PreviewRender {
  title: string;
  summary_lines: string[];
  audience?: string | null;
  body_markdown?: string | null;
  diff?: { field: string; before: unknown; after: unknown }[] | null;
  warnings: string[];
}
