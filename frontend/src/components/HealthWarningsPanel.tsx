import { formatIssueTimestamp, type HealthIssue } from '../services/health';

export interface HealthWarningsPanelProps {
  issues: HealthIssue[];
  title?: string;
  /** Cap the number shown; a "more" line points at the full System Health view. */
  limit?: number;
  emptyMessage?: string;
  onOpenHealth?: () => void;
}

const SEVERITY_CLASS: Record<HealthIssue['severity'], string> = {
  error: 'badge badge-error',
  warning: 'badge badge-stale',
  info: 'badge badge-loading',
};

/**
 * Renders grouped operational issues. Repetitive events are already collapsed by
 * `collectHealthIssues`, so this only decides how many to show.
 */
export function HealthWarningsPanel({
  issues,
  title = 'Active warnings',
  limit,
  emptyMessage = 'No active warnings. Everything the backend reports looks healthy.',
  onOpenHealth,
}: HealthWarningsPanelProps) {
  const shown = typeof limit === 'number' ? issues.slice(0, limit) : issues;
  const hidden = issues.length - shown.length;

  return (
    <section className="card" aria-labelledby="health-warnings-heading">
      <header className="card-header">
        <h2 id="health-warnings-heading">{title}</h2>
        <span
          className={issues.length > 0 ? 'badge badge-stale' : 'badge badge-connected'}
          data-testid="health-issue-count"
        >
          {issues.length}
        </span>
      </header>

      {issues.length === 0 ? (
        <p className="empty" data-testid="health-no-issues">
          {emptyMessage}
        </p>
      ) : (
        <ul className="health-issues" data-testid="health-issues">
          {shown.map((issue) => (
            <li key={issue.id} className="health-issue" data-severity={issue.severity}>
              <span className={SEVERITY_CLASS[issue.severity]}>{issue.severity}</span>
              <span className="health-issue-body">
                <span className="health-issue-source">{issue.source}</span>
                <span className="health-issue-message">{issue.message}</span>
                {issue.timestamp ? (
                  <span className="health-issue-time">{formatIssueTimestamp(issue.timestamp)}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}

      {hidden > 0 ? (
        <p className="footnote">
          +{hidden} more issue{hidden === 1 ? '' : 's'}
          {onOpenHealth ? (
            <>
              {' — '}
              <button type="button" className="link-button" onClick={onOpenHealth}>
                open System Health
              </button>
            </>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}
