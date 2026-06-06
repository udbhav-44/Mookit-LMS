# Sample UI — Editable Quiz Preview (Dev B)

The editable quiz-preview component + confirm dialog from the Dev B deliverables (B5.3). This is a
**sample/test** UI; the production chat UI is built by the mooKIT frontend team.

## Components
- `QuizPreview.tsx` — renders an `assessment_draft`; per question: **edit · regenerate · replace with
  similar · change type · change difficulty · view source · flag · delete**; a **provenance badge**
  ("AI-generated · edited by you") and **warnings** for higher-order / verification-flagged questions.
  Every action dispatches an `EditOp` (maps to the service's `edit_quiz` tool) which bumps the draft
  version.
- `ConfirmDialog.tsx` — faithful confirm dialog for any publish-tier action: the **audience chip** for
  announcements, the sanitized body, and a **diff table** for lecture publishing — rendered straight
  from the `PreviewRender` (Contract 3).
- `types.ts` — shared types mirroring the artifact payload + contracts.

## Wiring (with Dev A)
1. `POST /v1/chat` (SSE) — on `artifact_updated`, fetch the draft and render `QuizPreview`.
2. On `pending_confirmation`, render `ConfirmDialog` from the event's `preview`.
3. Confirm → `POST /v1/actions/{id}/confirm`; Reject → `/reject`.
4. Each `EditOp` → a follow-up `POST /v1/chat` turn invoking `edit_quiz` (re-drafting voids any
   outstanding confirm token by design).

## Run
```bash
npm install
npm run dev     # local preview
npm run test    # component tests (vitest + @testing-library/react)
```
