import { useEffect, useState } from 'react';
import { api } from '../services/api';

export function TradeHistoryPanel() {
  const [trades, setTrades] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState('');
  const [status, setStatus] = useState('');
  const [cycleId, setCycleId] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const load = async (reset = false) => {
    setLoading(true);
    setError(null);
    try {
      const currentOffset = reset ? 0 : offset;
      const [t, e] = await Promise.all([
        api.autoTrading.tradeHistory({ limit, offset: currentOffset, direction: direction || undefined, status: status || undefined, cycleId: cycleId || undefined }, undefined),
        api.autoTrading.tradeEvents(200),
      ]);
      if (reset) {
        setTrades(t.items ?? []);
        setOffset(limit);
      } else {
        setTrades((prev) => [...prev, ...(t.items ?? [])]);
        setOffset((prev) => prev + limit);
      }
      setEvents(e.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load trade history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction, status, cycleId]);

  const closedTrades = trades.filter((t) => t.status === 'closed');
  const wins = closedTrades.filter((t) => (t.net_profit ?? 0) > 0).length;
  const losses = closedTrades.filter((t) => (t.net_profit ?? 0) < 0).length;
  const winRate = closedTrades.length ? ((wins / closedTrades.length) * 100).toFixed(1) : 'Unavailable';
  const netPnl = closedTrades.reduce((sum, t) => sum + (t.net_profit ?? 0), 0);

  return (
    <section className="panel">
      <h2>Trade History</h2>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
        <select value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="">All directions</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
        </select>
        <input
          placeholder="Cycle ID"
          value={cycleId}
          onChange={(e) => setCycleId(e.target.value)}
        />
      </div>
      <div style={{ marginBottom: '0.5rem' }}>
        <strong>Closed:</strong> {closedTrades.length} | <strong>Wins:</strong> {wins} | <strong>Losses:</strong> {losses} | <strong>Win rate:</strong> {winRate}% | <strong>Net P/L:</strong> {netPnl.toFixed(2)}
      </div>
      {loading && <p>Loading...</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && trades.length === 0 && <p>No trades recorded yet.</p>}
      {trades.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Trade ID</th>
                <th>Cycle</th>
                <th>Dir</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Volume</th>
                <th>Initial SL</th>
                <th>Final SL</th>
                <th>Net P/L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.trade_id}>
                  <td>{trade.trade_id}</td>
                  <td>{trade.cycle_id ?? '-'}</td>
                  <td>{trade.direction ?? '-'}</td>
                  <td>{trade.actual_entry_price ?? 'Unavailable'}</td>
                  <td>{trade.actual_exit_price ?? 'Unavailable'}</td>
                  <td>{trade.actual_volume ?? trade.configured_lot_size ?? 'Unavailable'}</td>
                  <td>{trade.initial_sl ?? 'Unavailable'}</td>
                  <td>{trade.confirmed_initial_sl ?? trade.final_sl_before_exit ?? 'Unavailable'}</td>
                  <td>{trade.net_profit ?? 'Unavailable'}</td>
                  <td>{trade.status ?? 'Unavailable'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={() => load(false)} disabled={loading}>Load more</button>
        </div>
      )}
      {events.length > 0 && (
        <details>
          <summary>Event timeline ({events.length})</summary>
          <ul>
            {events.map((event) => (
              <li key={event.event_id}>
                {event.timestamp} — {event.event_type}
                {event.price != null ? ` @ ${event.price}` : ''}
                {event.result_code != null ? ` (rc=${event.result_code})` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}