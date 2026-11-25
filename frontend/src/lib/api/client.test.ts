import { describe, expect, it } from 'vitest';

import { cleanUserMessage } from './client';

describe('cleanUserMessage', () => {
  it('drops a leading rule reference', () => {
    expect(cleanUserMessage('G-21: item #1 decisions total 2 pc(s), it has 3 pc(s)')).toBe(
      'Item #1 decisions total 2 pc(s), it has 3 pc(s)',
    );
    expect(
      cleanUserMessage('DEC-69 (Q36): OP submits its own analysis of this goods slip first'),
    ).toBe('OP submits its own analysis of this goods slip first');
    expect(cleanUserMessage('Guard G-05: Hazardous items cannot be allowed')).toBe(
      'Hazardous items cannot be allowed',
    );
  });

  it('drops parenthesised rule references', () => {
    expect(cleanUserMessage('Only a user of OP analyses its goods (DEC-69)')).toBe(
      'Only a user of OP analyses its goods',
    );
    expect(cleanUserMessage('Mercury hazard (DEC-11, G-05) blocked')).toBe(
      'Mercury hazard blocked',
    );
  });

  it('keeps ordinary messages and item references', () => {
    expect(cleanUserMessage('Nothing changed')).toBe('Nothing changed');
    expect(cleanUserMessage('Item #2 (Cracked) is listed twice')).toBe(
      'Item #2 (Cracked) is listed twice',
    );
  });
});
