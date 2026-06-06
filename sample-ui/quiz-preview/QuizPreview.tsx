import { useState } from "react";
import type { AssessmentDraft, EditOp, Question, QuestionType } from "./types";

const HIGHER_ORDER = new Set(["analyze", "evaluate", "create"]);
const QUESTION_TYPES: QuestionType[] = [
  "mcq_single",
  "mcq_multi",
  "true_false",
  "fib",
  "descriptive",
];

interface Props {
  draft: AssessmentDraft;
  /** Dispatch an edit operation back to the service (EditQuizTool). */
  onEdit: (op: EditOp) => void;
  /** Open the source span for a citation ("view source"). */
  onViewSource: (q: Question) => void;
  /** Open the confirm dialog for publishing. */
  onPublish: () => void;
}

/** Provenance badge: "AI-generated · edited by you". */
function ProvenanceBadge({ draft }: { draft: AssessmentDraft }) {
  const label = draft.provenance.edited_by_human
    ? "AI-generated · edited by you"
    : "AI-generated";
  return <span className="qp-badge" title={draft.provenance.label}>{label}</span>;
}

function QuestionCard({
  q,
  index,
  onEdit,
  onViewSource,
}: {
  q: Question;
  index: number;
  onEdit: (op: EditOp) => void;
  onViewSource: (q: Question) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.questionText);
  const higherOrder = HIGHER_ORDER.has(q.bloom_level);

  return (
    <li className="qp-card" data-type={q.questionType}>
      <div className="qp-card-head">
        <span className="qp-type">{q.questionType}</span>
        <span className="qp-bloom" data-higher={higherOrder}>{q.bloom_level}</span>
        {q.flags.length > 0 && (
          <span className="qp-flags" title={q.flags.join(", ")}>
            ⚠ {q.flags.length} flag(s)
          </span>
        )}
      </div>

      {editing ? (
        <textarea
          className="qp-edit"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            setEditing(false);
            if (text !== q.questionText) onEdit({ op: "edit_text", index, questionText: text });
          }}
        />
      ) : (
        <p className="qp-text" onClick={() => setEditing(true)}>
          {q.questionText}
        </p>
      )}

      {q.options && (
        <ul className="qp-options">
          {q.options.map((o, i) => (
            <li key={i} className={o.isCorrect ? "correct" : "distractor"}>
              {o.isCorrect ? "✓" : "○"} {o.optionText}
              {o.misconception && <em className="qp-misc"> — {o.misconception}</em>}
            </li>
          ))}
        </ul>
      )}

      <div className="qp-actions">
        <button onClick={() => setEditing(true)}>Edit</button>
        <button onClick={() => onEdit({ op: "regenerate", index })}>Regenerate</button>
        <button onClick={() => onEdit({ op: "replace_similar", index })}>Replace with similar</button>
        <select
          aria-label="Change type"
          value={q.questionType}
          onChange={(e) => onEdit({ op: "change_type", index, qtype: e.target.value as QuestionType })}
        >
          {QUESTION_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <button onClick={() => onViewSource(q)}>View source</button>
        <button
          className="qp-flag"
          onClick={() => onEdit({ op: "flag", index, reason: "instructor_flag" })}
        >
          Flag
        </button>
        <button className="qp-danger" onClick={() => onEdit({ op: "remove", index })}>
          Delete
        </button>
      </div>
    </li>
  );
}

export default function QuizPreview({ draft, onEdit, onViewSource, onPublish }: Props) {
  const questions = draft.payload.questions;
  return (
    <section className="qp-root">
      <header className="qp-header">
        <h2>{draft.title}</h2>
        <ProvenanceBadge draft={draft} />
        <span className="qp-version">v{draft.version}</span>
      </header>

      {draft.payload.warnings.length > 0 && (
        <ul className="qp-warnings">
          {draft.payload.warnings.map((w, i) => (
            <li key={i}>⚠ {w}</li>
          ))}
        </ul>
      )}

      <div className="qp-knobs">
        <label>
          Difficulty
          <select
            onChange={(e) =>
              onEdit({ op: "set_difficulty", difficulty: e.target.value as "easy" | "medium" | "hard" | "mixed" })
            }
            defaultValue="medium"
          >
            <option value="easy">easy</option>
            <option value="medium">medium</option>
            <option value="hard">hard</option>
            <option value="mixed">mixed</option>
          </select>
        </label>
        <button onClick={() => onEdit({ op: "add", qtype: "mcq_single", delta: 1 })}>+ Add MCQ</button>
      </div>

      <ol className="qp-list">
        {questions.map((q, i) => (
          <QuestionCard key={i} q={q} index={i} onEdit={onEdit} onViewSource={onViewSource} />
        ))}
      </ol>

      <footer className="qp-footer">
        <button className="qp-publish" onClick={onPublish}>
          Add to course…
        </button>
      </footer>
    </section>
  );
}
