import type { AutoTradingStatus } from '../types/market';
import { formatDateTime } from '../services/format';
import { Pill } from './terminal/ui';

interface StrategyCyclePanelProps {
  status: AutoTradingStatus | null;
}

/**
 * The strategy cycle, shown as the three phases the backend actually runs:
 * levels built (Value) → one side triggered and the opposing entry removed
 * (Removing) → exit confirmed and the next cycle prepared (Switching).
 *
 * The authoritative source is `strategy_phase` from the backend response; the
 * stepper never invents a transition the backend did not report. Phases this
 * build of the backend does not define are rendered verbatim as "unknown".
 */

interface PhaseStep {
  /** Backend phase values that map to this step. */
  phases: string[];
  key: string;
  name: string;
  detail: string;
}

const STEPS: PhaseStep[] = [
  {
    phases: ['INITIALIZING'],
    key: 'initializing',
    name: 'Preparing',
    detail: 'Building cycle levels from a fresh reference price.',
  },
  {
    phases: ['WAITING_ENTRY'],
    key: 'value',
    name: 'Phase A · Value',
    detail: 'Buy and Sell Stop entries armed around the reference price.',
  },
  {
    phases: ['BUY_OPEN', 'SELL_OPEN'],
    key: 'removing',
    name: 'Phase B · Removing',
    detail: 'One entry triggered; the opposing pending entry is being removed.',
  },
  {
    phases: ['SWITCHING'],
    key: 'switching',
    name: 'Phase C · Switching',
    detail: 'Stop-loss exit confirmed; the next cycle is being prepared.',
  },
];

function activeStepIndex(phase: string | null | undefined): number {
  if (!phase) {
    return -1;
  }
  return STEPS.findIndex((step) => step.phases.includes(phase));
}

export function StrategyCyclePanel({ status }: StrategyCyclePanelProps) {
  const phase = status?.strategy_phase ?? null;
  const stepIndex = activeStepIndex(phase);
  const knownPhase = phase !== null && stepIndex !== -1;
  const activeStep = stepIndex >= 0 ? STEPS[stepIndex] : null;
  const positionOpen = (status?.position_ticket ?? null) !== null;
  const pendingSides = [
    status?.buy_order_ticket != null ? 'buy' : null,
    status?.sell_order_ticket != null ? 'sell' : null,
  ].filter((side): side is string => side !== null);

  return (
    <section className="card" aria-labelledby="cycle-heading">
      <header className="card-header">
        <h2 id="cycle-heading">Strategy cycle</h2>
        <Pill
          tone={phase === 'ERROR' ? 'negative' : knownPhase ? 'accent' : 'neutral'}
          testId="cycle-phase-pill"
          title="Verbatim strategy phase reported by the backend"
        >
          {phase ?? 'unknown'}
        </Pill>
      </header>

      <ol className="stepper" data-testid="cycle-stepper">
        {STEPS.map((step, index) => {
          const state =
            index === stepIndex ? 'active' : stepIndex > index ? 'done' : 'upcoming';
          return (
            <li
              key={step.key}
              className={`step step-${state}`}
              data-testid={`cycle-step-${step.key}`}
              aria-current={state === 'active' ? 'step' : undefined}
            >
              <span className="step-marker" aria-hidden="true" />
              <span className="step-body">
                <span className="step-name">{step.name}</span>
                <span className="step-detail">{step.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>

      {!knownPhase && phase !== null ? (
        <p className="alert alert-warning" data-testid="cycle-phase-unknown">
          The backend reported strategy phase <code>{phase}</code>, which this dashboard does not
          map to a cycle step. Showing the raw value rather than guessing a transition.
        </p>
      ) : null}

      {status === null ? (
        <p className="empty" data-testid="cycle-empty">
          Auto-trading status is not available yet, so the cycle state cannot be shown.
        </p>
      ) : (
        <dl className="kv kv-compact">
          <div>
            <dt>Cycle ID</dt>
            <dd data-testid="cycle-id">{status.cycle_id ?? '—'}</dd>
          </div>
          <div>
            <dt>Reference price</dt>
            <dd data-testid="cycle-reference">{formatLevel(status.reference_value)}</dd>
          </div>
          <div>
            <dt>Active direction</dt>
            <dd data-testid="cycle-active-side">{status.active_side ?? '—'}</dd>
          </div>
          <div>
            <dt>Position open</dt>
            <dd data-testid="cycle-position-open">
              {positionOpen ? `yes · #${status.position_ticket}` : 'no'}
            </dd>
          </div>
          <div>
            <dt>Pending entries</dt>
            <dd data-testid="cycle-pending">
              {pendingSides.length > 0 ? pendingSides.join(' + ') : 'none listed'}
            </dd>
          </div>
          <div>
            <dt>Next cycle at</dt>
            <dd data-testid="cycle-next">{formatDateTime(status.next_cycle)}</dd>
          </div>
        </dl>
      )}

      {activeStep ? (
        <p className="card-detail cycle-step-context" data-testid="cycle-step-detail">
          {activeStep.detail}
        </p>
      ) : null}
    </section>
  );
}

function formatLevel(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
}
