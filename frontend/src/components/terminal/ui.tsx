/**
 * Shared display primitives.
 *
 * Kept deliberately small: the read-only screen needs a status pill and an
 * honest empty/error block. The rule that matters most: a value the backend did
 * not supply renders as an em dash with a screen-reader hint - never as zero.
 */

import type { ReactNode } from 'react';

/* ---------------------------------------------------------------------------
   Pill
   --------------------------------------------------------------------------- */

export type PillTone = 'positive' | 'negative' | 'warning' | 'neutral' | 'accent' | 'info';

export interface PillProps {
  tone: PillTone;
  children: ReactNode;
  title?: string;
  testId?: string;
}

export function Pill({ tone, children, title, testId }: PillProps) {
  return (
    <span className={`pill pill-${tone}`} title={title} data-testid={testId}>
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   State blocks - loading, empty and error.
   --------------------------------------------------------------------------- */

export interface StateBlockProps {
  title: string;
  detail?: string | null;
  tone?: 'neutral' | 'error';
  children?: ReactNode;
  testId?: string;
}

export function StateBlock({ title, detail, tone = 'neutral', children, testId }: StateBlockProps) {
  return (
    <div
      className={tone === 'error' ? 'state-block state-block-error' : 'state-block'}
      data-testid={testId}
      role={tone === 'error' ? 'alert' : undefined}
    >
      <span className="state-block-title">{title}</span>
      {detail ? <span className="state-block-detail">{detail}</span> : null}
      {children}
    </div>
  );
}

