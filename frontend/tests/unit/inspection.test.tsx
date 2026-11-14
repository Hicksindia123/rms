import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { QuantityReconciliationMeter } from '@/features/inspection/QuantityReconciliationMeter';
import { HazardBanner } from '@/features/inspection/HazardBanner';
import { EnclosedOvalToggle } from '@/features/inspection/EnclosedOvalToggle';
import { ExtractionSection } from '@/features/inspection/ExtractionSection';
import { NotAllowedModal } from '@/features/inspection/NotAllowedModal';
import type { ConditionOption } from '@/features/inspection/types';

describe('Step-3 Inspection Components (P2-05)', () => {
  describe('QuantityReconciliationMeter', () => {
    it('shows under-allocated state when gradedQty < receivedQty', () => {
      render(<QuantityReconciliationMeter receivedQty={10} gradedQty={7} />);
      expect(screen.getByText(/Under-allocated: 7 \/ 10 \(3 remaining\)/)).toBeInTheDocument();
      expect(screen.getByText(/70% allocated/)).toBeInTheDocument();
    });

    it('shows reconciled match when gradedQty === receivedQty', () => {
      render(<QuantityReconciliationMeter receivedQty={10} gradedQty={10} />);
      expect(screen.getByText(/Reconciled: 10 \/ 10 pieces graded/)).toBeInTheDocument();
      expect(screen.getByText(/100% allocated/)).toBeInTheDocument();
    });

    it('shows over-allocated state when gradedQty > receivedQty', () => {
      render(<QuantityReconciliationMeter receivedQty={10} gradedQty={12} />);
      expect(screen.getByText(/Over-allocated: 12 \/ 10 \(\+2 pieces over\)/)).toBeInTheDocument();
    });

    it('displays DMT shortage note separately from physical reconciliation', () => {
      render(
        <QuantityReconciliationMeter
          receivedQty={10}
          gradedQty={10}
          shortQtyDiscrepancy={2}
          shortQtyRuleText="Documented shortage; does not count against physical received pieces."
        />,
      );
      expect(screen.getByText(/Documented Shortage:/)).toBeInTheDocument();
      expect(screen.getByText(/2 pcs noted/)).toBeInTheDocument();
      expect(
        screen.getByText(/does not count against physical received pieces/),
      ).toBeInTheDocument();
    });
  });

  describe('HazardBanner', () => {
    it('displays mercury hazard alert with piece count', () => {
      render(<HazardBanner hazardQty={2} />);
      expect(
        screen.getByText(/MERCURY HAZARD — QUARANTINE PROTOCOL ACTIVATED/),
      ).toBeInTheDocument();
      expect(screen.getByText(/2 pieces/)).toBeInTheDocument();
      expect(screen.getByText(/Non-bypassable Safety Guard Active/)).toBeInTheDocument();
    });
  });

  describe('EnclosedOvalToggle', () => {
    it('shows locked state when unconfirmed', () => {
      render(<EnclosedOvalToggle idPrefix="t" confirmed={false} onChange={vi.fn()} />);
      expect(
        screen.getByText(/You must confirm full opening of the enclosed oval thermometer/i),
      ).toBeInTheDocument();
      const checkbox = screen.getByLabelText(/Confirm Enclosed Oval full opening/i);
      expect(checkbox).not.toBeChecked();
    });

    it('calls onChange when user confirms full opening', () => {
      const onChange = vi.fn();
      render(<EnclosedOvalToggle idPrefix="t" confirmed={false} onChange={onChange} />);
      const checkbox = screen.getByLabelText(/Confirm Enclosed Oval full opening/i);
      fireEvent.click(checkbox);
      expect(onChange).toHaveBeenCalledWith(true);
    });

    it('shows unlocked confirmation when confirmed', () => {
      render(<EnclosedOvalToggle idPrefix="t" confirmed={true} onChange={vi.fn()} />);
      expect(screen.getByText(/Condition grading unlocked/i)).toBeInTheDocument();
    });
  });

  describe('ExtractionSection', () => {
    it('displays reconciled state when packaging + container = target', () => {
      render(
        <ExtractionSection
          idPrefix="t"
          primaryType="PACKAGING_EXTRACTED"
          packagingQty={7}
          containerQty={3}
          targetQty={10}
          onPrimaryTypeChange={vi.fn()}
          onPackagingQtyChange={vi.fn()}
          onContainerQtyChange={vi.fn()}
        />,
      );
      expect(screen.getByText(/Reconciled \(10\/10\)/)).toBeInTheDocument();
    });

    it('displays discrepancy when extraction sum != target', () => {
      render(
        <ExtractionSection
          idPrefix="t"
          primaryType="CONTAINER_EXTRACTED"
          packagingQty={4}
          containerQty={3}
          targetQty={10}
          onPrimaryTypeChange={vi.fn()}
          onPackagingQtyChange={vi.fn()}
          onContainerQtyChange={vi.fn()}
        />,
      );
      expect(screen.getByText(/3 remaining \(7\/10\)/)).toBeInTheDocument();
    });

    it('triggers callback on primary type change', () => {
      const onPrimaryChange = vi.fn();
      render(
        <ExtractionSection
          idPrefix="t"
          primaryType="PACKAGING_EXTRACTED"
          packagingQty={10}
          containerQty={0}
          targetQty={10}
          onPrimaryTypeChange={onPrimaryChange}
          onPackagingQtyChange={vi.fn()}
          onContainerQtyChange={vi.fn()}
        />,
      );
      const containerRadio = screen.getByLabelText(/Container Extracted/i);
      fireEvent.click(containerRadio);
      expect(onPrimaryChange).toHaveBeenCalledWith('CONTAINER_EXTRACTED');
    });
  });

  describe('NotAllowedModal', () => {
    const mockOption: ConditionOption = {
      code: 'DMT_OTHER_BRANDS',
      label: 'Other Brands Found',
      allowed_status: 'NO',
      system_behavior: 'REJECT_HOLD',
      rule_text: 'Other brand pieces received; rejected for party return',
      next_action_text: 'Hold for party return',
      remarks: null,
      sort_order: 3,
    };

    it('shows downstream routing message on not-allowed condition', () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();
      render(
        <NotAllowedModal
          isOpen={true}
          option={mockOption}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />,
      );
      expect(screen.getByText(/Not Allowed Condition Selected/)).toBeInTheDocument();
      expect(
        screen.getByText(/will be moved to REJECTED_HOLD for return to the sending party/),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Confirm Allocation/i }));
      expect(onConfirm).toHaveBeenCalled();
    });
  });
});
