import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DynamicForm } from '@/components/erp/DynamicForm';
import type { FormSnapshot } from '@/features/config/forms/types';

describe('DynamicForm Component', () => {
  const sampleSnapshot: FormSnapshot = {
    form_code: 'TEST_GATE_INWARD',
    name: 'Gate Inward Test Form',
    version: 1,
    status: 'PUBLISHED',
    fields: [
      {
        field_key: 'station_code',
        label: 'Receiving Station',
        control_type: 'text',
        sort_order: 10,
        required: true,
      },
      {
        field_key: 'delivery_mode',
        label: 'Mode of Delivery',
        control_type: 'dropdown',
        sort_order: 20,
        required: true,
        options: [
          {
            code: 'COURIER',
            label: 'Courier / Parcel',
            sort_order: 10,
            allowed_status: 'YES',
          },
          {
            code: 'DIRECT_TRUCK',
            label: 'Direct Transport / Truck',
            sort_order: 20,
            allowed_status: 'CONDITIONAL',
            rule_text: 'Vehicle details and docket mandatory',
          },
          {
            code: 'CUSTOMER_HAND',
            label: 'Direct Handover',
            sort_order: 30,
            allowed_status: 'NO',
            rule_text: 'Customer handover suspended at this hub',
          },
        ],
      },
      {
        field_key: 'courier_name',
        label: 'Courier Company Name',
        control_type: 'text',
        sort_order: 30,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'COURIER' },
        required_when: { field: 'delivery_mode', op: 'eq', value: 'COURIER' },
      },
      {
        field_key: 'vehicle_no',
        label: 'Vehicle Registration Number',
        control_type: 'text',
        sort_order: 40,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
        required_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
      },
      {
        field_key: 'transporter_name',
        label: 'Transporter Name',
        control_type: 'text',
        sort_order: 50,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
      },
    ],
  };

  it('renders initial form fields and hides conditional fields when condition is not met', () => {
    render(<DynamicForm formSnapshot={sampleSnapshot} />);

    expect(screen.getByLabelText(/Receiving Station/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Mode of Delivery/i)).toBeInTheDocument();

    // Courier and Truck fields should initially be hidden
    expect(screen.queryByLabelText(/Courier Company Name/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Vehicle Registration Number/i)).not.toBeInTheDocument();
  });

  it('toggles conditional visibility dynamically when delivery mode changes', async () => {
    render(<DynamicForm formSnapshot={sampleSnapshot} />);

    const select = screen.getByLabelText(/Mode of Delivery/i);

    // Select DIRECT_TRUCK
    fireEvent.change(select, { target: { value: 'DIRECT_TRUCK' } });

    await waitFor(() => {
      expect(screen.getByLabelText(/Vehicle Registration Number/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Transporter Name/i)).toBeInTheDocument();
      expect(screen.queryByLabelText(/Courier Company Name/i)).not.toBeInTheDocument();
    });

    // Check helper rule_text and badge for CONDITIONAL
    expect(screen.getByText(/Vehicle details and docket mandatory/i)).toBeInTheDocument();
    expect(screen.getByText('Conditional')).toBeInTheDocument();

    // Switch to COURIER
    fireEvent.change(select, { target: { value: 'COURIER' } });

    await waitFor(() => {
      expect(screen.getByLabelText(/Courier Company Name/i)).toBeInTheDocument();
      expect(screen.queryByLabelText(/Vehicle Registration Number/i)).not.toBeInTheDocument();
    });
  });

  it('shows "Not allowed" badge for disallowed options', async () => {
    render(<DynamicForm formSnapshot={sampleSnapshot} />);

    const select = screen.getByLabelText(/Mode of Delivery/i);
    fireEvent.change(select, { target: { value: 'CUSTOMER_HAND' } });

    await waitFor(() => {
      expect(screen.getByText('Not allowed')).toBeInTheDocument();
      expect(screen.getByText(/Customer handover suspended at this hub/i)).toBeInTheDocument();
    });
  });

  it('validates required conditional fields on submission', async () => {
    const handleSubmit = vi.fn();
    render(<DynamicForm formSnapshot={sampleSnapshot} onSubmit={handleSubmit} />);

    // Fill station
    fireEvent.change(screen.getByLabelText(/Receiving Station/i), {
      target: { value: 'BLR-01' },
    });

    // Select DIRECT_TRUCK (makes vehicle_no required)
    fireEvent.change(screen.getByLabelText(/Mode of Delivery/i), {
      target: { value: 'DIRECT_TRUCK' },
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/Vehicle Registration Number/i)).toBeInTheDocument();
    });

    // Submit while vehicle_no is empty
    fireEvent.click(screen.getByRole('button', { name: /Submit/i }));

    await waitFor(() => {
      expect(screen.getByText(/Vehicle Registration Number is required/i)).toBeInTheDocument();
    });
    expect(handleSubmit).not.toHaveBeenCalled();

    // Now fill vehicle_no
    fireEvent.change(screen.getByLabelText(/Vehicle Registration Number/i), {
      target: { value: 'KA-01-AB-1234' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Submit/i }));

    await waitFor(() => {
      expect(handleSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          station_code: 'BLR-01',
          delivery_mode: 'DIRECT_TRUCK',
          vehicle_no: 'KA-01-AB-1234',
        }),
      );
    });
  });
});
