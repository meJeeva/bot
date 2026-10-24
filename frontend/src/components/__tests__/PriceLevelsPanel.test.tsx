import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeAutoTradingStatus } from '../../test/fixtures';
import { PriceLevelsPanel } from '../PriceLevelsPanel';

describe('PriceLevelsPanel', () => {
  it('renders the strategy-calculated levels with broker digits', () => {
    render(<PriceLevelsPanel status={makeAutoTradingStatus()} digits={2} />);

    expect(screen.getByTestId('levels-strategy-title')).toBeInTheDocument();
    expect(screen.getByTestId('level-reference')).toHaveTextContent('4186.14');
    expect(screen.getByTestId('level-buy-entry')).toHaveTextContent('4187.14');
    expect(screen.getByTestId('level-buy-sl')).toHaveTextContent('4186.14');
    expect(screen.getByTestId('level-sell-entry')).toHaveTextContent('4185.14');
    expect(screen.getByTestId('level-sell-sl')).toHaveTextContent('4186.14');
  });

  it('keeps submitted tickets distinct from calculated and confirmed values', () => {
    render(
      <PriceLevelsPanel
        status={makeAutoTradingStatus({ buy_order_ticket: 630101, sell_order_ticket: null })}
        digits={2}
      />,
    );

    expect(screen.getByTestId('levels-submitted-title')).toBeInTheDocument();
    expect(screen.getByTestId('level-buy-ticket')).toHaveTextContent('#630101');
    expect(screen.getByTestId('level-sell-ticket')).toHaveTextContent('—');
    expect(screen.getByTestId('levels-confirmed-title')).toBeInTheDocument();
  });

  it('shows broker-filled data only in the confirmed group', () => {
    render(
      <PriceLevelsPanel
        status={makeAutoTradingStatus({
          position_ticket: 5001,
          entry_price: 4187.14,
          entry_time: '2026-10-12T05:41:12.000Z',
          break_even_active: true,
          break_even_level: 4187.14,
        })}
        digits={2}
      />,
    );

    expect(screen.getByTestId('level-position-ticket')).toHaveTextContent('#5001');
    expect(screen.getByTestId('level-entry-price')).toHaveTextContent('4187.14');
    expect(screen.getByTestId('level-break-even')).toHaveTextContent('4187.14');
    expect(screen.getByTestId('level-break-even')).toHaveTextContent('active');
  });

  it('marks break-even as not active without inventing a level', () => {
    render(
      <PriceLevelsPanel
        status={makeAutoTradingStatus({ break_even_active: false, break_even_level: null })}
        digits={2}
      />,
    );

    const level = screen.getByTestId('level-break-even');
    expect(level).toHaveTextContent('—');
    expect(level).toHaveTextContent('not active');
    expect(level).not.toHaveTextContent('418');
  });

  it('renders missing levels as placeholders, never as zero', () => {
    render(
      <PriceLevelsPanel
        status={makeAutoTradingStatus({
          highest_favorable_price: null,
          lowest_favorable_price: null,
        })}
        digits={2}
      />,
    );

    expect(screen.getByTestId('level-high-water')).toHaveTextContent('—');
    expect(screen.getByTestId('level-high-water')).not.toHaveTextContent('0');
    expect(screen.getByTestId('level-low-water')).toHaveTextContent('—');
  });

  it('explains that no cycle has been built yet when levels are absent', () => {
    render(
      <PriceLevelsPanel
        status={makeAutoTradingStatus({
          reference_value: null,
          buy_entry: null,
          sell_entry: null,
        })}
        digits={2}
      />,
    );

    expect(screen.getByTestId('levels-no-cycle')).toBeInTheDocument();
  });

  it('states that the status payload itself is unavailable when null', () => {
    render(<PriceLevelsPanel status={null} digits={2} />);

    expect(screen.getByTestId('levels-empty')).toBeInTheDocument();
  });
});
