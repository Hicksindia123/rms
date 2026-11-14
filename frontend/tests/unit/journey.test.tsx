import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { JourneyEntry, MyJourney } from '@/features/journey/api';
import { JourneyBoard } from '@/features/journey/JourneyHome';
import { entryPath, entryTab, itemPath } from '@/features/journey/screens';

// Change plan Phase 10 (AMD-22): role journeys. Menu labels/order come from the API (DB config);
// the frontend only maps screen keys to routes.

function entry(partial: Partial<JourneyEntry> & { code: string }): JourneyEntry {
  return {
    label: partial.code,
    hint: null,
    kind: 'STEP',
    screen_key: 'journey-queue',
    item_screen_key: 'gs-detail',
    queue_code: partial.code,
    count: 0,
    next: null,
    ...partial,
  };
}

describe('journey screens', () => {
  it('maps menu entries to routes', () => {
    expect(entryPath(entry({ code: 'COUNTING' }))).toBe('/mywork?journey=COUNTING');
    expect(entryPath(entry({ code: 'GATE_ENTRY', screen_key: 'gs-new' }))).toBe('/gs/new');
    expect(entryPath(entry({ code: 'AUDIT', screen_key: 'audit' }))).toBe('/admin/audit');
    expect(entryPath(entry({ code: 'X', screen_key: 'unknown-screen' }))).toBe('/mywork');
    expect(entryTab(entry({ code: 'DR', screen_key: 'department-routing' }))).toBe(
      'department-routing',
    );
  });

  it('opens the right screen for the next GS', () => {
    const item = { gs_id: 'g1', target_id: 't1' };
    expect(itemPath('gs-unboxing', item)).toBe('/gs/g1/unboxing');
    expect(itemPath('gs-itemization', item)).toBe('/gs/g1/itemization');
    expect(itemPath('custody-transfer', item)).toBe('/custody/transfers/t1');
    expect(itemPath('accounts-entry-gs', item)).toBe('/accounts-entry/g1');
    expect(itemPath(null, item)).toBe('/gs/g1');
  });
});

describe('<JourneyBoard />', () => {
  const journey: MyJourney = {
    hidden_features: [],
    entries: [
      entry({ code: 'CARTON_OPENING', label: 'Carton Opening', item_screen_key: 'gs-unboxing' }),
      entry({
        code: 'COUNTING',
        label: 'Counting',
        item_screen_key: 'gs-itemization',
        count: 2,
        next: {
          gs_id: 'g9',
          gs_no: 'GS-0009',
          party_name: 'Party A',
          station_name: null,
          target_id: 'g9',
          since: '2026-11-11T00:00:00Z',
        },
      }),
      entry({
        code: 'REPORTS',
        label: 'Reports',
        kind: 'TOOL',
        screen_key: 'reports',
        queue_code: null,
        item_screen_key: null,
        count: null,
      }),
    ],
  };

  it('shows the steps in journey order with counts and one primary action', () => {
    const onNavigate = vi.fn();
    render(
      <JourneyBoard
        journey={journey}
        now={Date.parse('2026-11-14T00:00:00Z')}
        onNavigate={onNavigate}
      />,
    );
    const cards = screen.getAllByTestId('journey-step');
    expect(cards.map((c) => c.dataset.step)).toEqual(['CARTON_OPENING', 'COUNTING']); // tools are not steps
    const [opening, counting] = cards;
    expect(opening?.textContent).toContain('Nothing waiting');
    expect(counting?.textContent).toContain('Next: GS-0009 · Party A · waiting 3d');
    expect(counting?.textContent).toContain('2');

    const primaries = document.querySelectorAll('.btn--primary');
    expect(primaries).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Open next Counting: GS-0009' }));
    expect(onNavigate).toHaveBeenCalledWith('/gs/g9/itemization');
    fireEvent.click(screen.getByRole('button', { name: 'View all 2 at Counting' }));
    expect(onNavigate).toHaveBeenCalledWith('/mywork?journey=COUNTING');
  });

  it('renders nothing for a role without journey steps', () => {
    const { container } = render(
      <JourneyBoard journey={{ entries: [], hidden_features: [] }} now={0} onNavigate={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
