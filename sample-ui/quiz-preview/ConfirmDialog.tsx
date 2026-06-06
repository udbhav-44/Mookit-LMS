import type { PreviewRender } from "./types";

interface Props {
  preview: PreviewRender;
  onConfirm: () => void;
  onReject: () => void;
}

/**
 * Faithful confirm dialog for any publish-tier action. Renders exactly what the service will send:
 *  - announcements: audience chip + channel + sanitized body
 *  - lectures: a diff/change-summary table
 *  - assessments: a per-question summary + warnings
 */
export default function ConfirmDialog({ preview, onConfirm, onReject }: Props) {
  return (
    <div className="cd-overlay" role="dialog" aria-modal="true" aria-label={preview.title}>
      <div className="cd-card">
        <h3>{preview.title}</h3>

        {preview.audience && (
          <div className="cd-audience-chip">To: {preview.audience}</div>
        )}

        {preview.summary_lines.length > 0 && (
          <ul className="cd-summary">
            {preview.summary_lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}

        {preview.body_markdown && (
          <pre className="cd-body">{preview.body_markdown}</pre>
        )}

        {preview.diff && preview.diff.length > 0 && (
          <table className="cd-diff">
            <thead>
              <tr><th>Field</th><th>Before</th><th>After</th></tr>
            </thead>
            <tbody>
              {preview.diff.map((d, i) => (
                <tr key={i}>
                  <td>{d.field}</td>
                  <td>{String(d.before ?? "—")}</td>
                  <td>{String(d.after ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {preview.warnings.length > 0 && (
          <ul className="cd-warnings">
            {preview.warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        )}

        <div className="cd-actions">
          <button className="cd-reject" onClick={onReject}>Cancel</button>
          <button className="cd-confirm" onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}
