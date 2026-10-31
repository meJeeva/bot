import { useEffect, useState } from 'react';

import { api, describeError } from '../services/api';
import type { AutoTradingStatus } from '../types/market';

interface HistoryItem {
  cycle_id?: string | null;
  symbol?: string | null;
  status?: string | null;
  entry_price?: number | null;
  exit_time?: string | null;
  error?: string | null;
}


const POLL_MS = 2000;

export function AutoTradingPanel() {
  const [status, setStatus] = useState<AutoTradingStatus | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [next, historyResponse] = await Promise.all([
        api.autoTrading.status(),
        api.autoTrading.history(),
      ]);
      setStatus(next);
      setHistory((historyResponse.items ?? []) as HistoryItem[]);
      setError(null);
    } catch (cause) {
      setError(describeError(cause));
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const start = async () => {
    setBusy(true);
    try {
      const next = await api.autoTrading.start();
      setStatus(next);
      setError(null);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!window.confirm('Stop auto trading?')) return;
    setBusy(true);
    try {
      const next = await api.autoTrading.stop();
      setStatus(next);
      setError(null);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  const currentStatus = status?.status ?? 'STOPPED';
  const canStart = currentStatus === 'STOPPED' || currentStatus === 'ERROR';
  const canStop =
    currentStatus === 'RUNNING' ||
    currentStatus === 'STARTING' ||
    currentStatus === 'STOPPING';

  return (
    <section className="card auto-trading-card" aria-labelledby="auto-trading-heading">
      <header className="card-header">
        <div>
          <h2 id="auto-trading-heading">Auto Trading Control</h2>
          <p className="card-detail">M1 Trend Pullback · XAUUSD · DEMO</p>
        </div>
        <span className="status-pill" data-testid="auto-trading-status">
          {currentStatus}
        </span>
      </header>

      {error ? (
        <p className="alert alert-error" data-testid="auto-trading-error">
          {error}
        </p>
      ) : null}

      <div className="auto-trading-layout">
        <div className="control-actions">
          <button
            type="button"
            className="button button-primary"
            data-testid="start-auto-trading"
            onClick={() => void start()}
            disabled={busy || !canStart}
          >
            {busy && canStart ? 'Starting…' : 'Start Auto Trading'}
          </button>
          <button
            type="button"
            className="button button-danger"
            data-testid="stop-auto-trading"
            onClick={() => void stop()}
            disabled={busy || !canStop}
          >
            {busy && canStop ? 'Stopping…' : 'Stop Auto Trading'}
          </button>
        </div>

        <dl className="kv">
          <div><dt>Symbol</dt><dd data-testid="auto-symbol">{status?.symbol ?? '—'}</dd></div>
          <div><dt>Timeframe</dt><dd data-testid="auto-timeframe">{status?.timeframe ?? '5s'}</dd></div>
          <div><dt>Balance</dt><dd data-testid="auto-balance">{status?.balance ?? '—'}</dd></div>
          <div><dt>Equity</dt><dd data-testid="auto-equity">{status?.equity ?? '—'}</dd></div>
          <div><dt>Position status</dt><dd data-testid="auto-position-status">{status?.position_status ?? 'none'}</dd></div>
          <div><dt>Position ticket</dt><dd data-testid="auto-position-ticket">{status?.position_ticket ?? '—'}</dd></div>
          <div><dt>Entry price</dt><dd data-testid="auto-entry-price">{status?.entry_price ?? '—'}</dd></div>
          <div><dt>Entry time</dt><dd data-testid="auto-entry-time">{status?.entry_time ?? '—'}</dd></div>
          <div><dt>Current P/L</dt><dd data-testid="auto-profit">{status?.current_profit ?? '—'}</dd></div>
          <div><dt>Completed cycles</dt><dd data-testid="auto-completed-cycles">{status?.completed_cycles ?? 0}</dd></div>
          <div><dt>Successful entries</dt><dd data-testid="auto-successful-entries">{status?.successful_entries ?? 0}</dd></div>
          <div><dt>Failed entries</dt><dd data-testid="auto-failed-entries">{status?.failed_entries ?? 0}</dd></div>
          <div><dt>Failed exits</dt><dd data-testid="auto-failed-exits">{status?.failed_exits ?? 0}</dd></div>
          <div><dt>Last entry</dt><dd data-testid="auto-last-entry">{status?.last_entry_result ?? '—'}</dd></div>
          <div><dt>Last exit</dt><dd data-testid="auto-last-exit">{status?.last_exit_result ?? '—'}</dd></div>
          <div><dt>Next cycle</dt><dd data-testid="auto-next-cycle">{status?.next_cycle ?? '—'}</dd></div>
          <div><dt>Last error</dt><dd data-testid="auto-last-error">{status?.last_error ?? '—'}</dd></div>
        </dl>
      </div>

      <section className="history-section" aria-labelledby="trade-history-heading">
        <header className="card-header">
          <h3 id="trade-history-heading">Trade History</h3>
          <span className="badge">{history.length} records</span>
        </header>
        {history.length === 0 ? (
          <p className="empty" data-testid="trade-history-empty">
            No trade history available.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Cycle</th>
                  <th>Symbol</th>
                  <th>Status</th>
                  <th>Entry</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item, index) => (
                  <tr key={item.cycle_id ?? index}>
                    <td>{item.cycle_id ?? '—'}</td>
                    <td>{item.symbol ?? '—'}</td>
                    <td>{item.status ?? '—'}</td>
                    <td>{item.entry_price ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}