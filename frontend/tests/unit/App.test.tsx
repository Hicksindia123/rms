import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from '@/app/App';

describe('<App />', () => {
  it('renders the sign-in page for a signed-out visitor', async () => {
    render(<App />);
    // The session check is asynchronous: a calm loader first, then the form.
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Sign in' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    // Production audit 2026-11-14 (B11): no unverifiable claims and no dead controls.
    expect(screen.queryByText(/2FA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Remember workstation/i)).not.toBeInTheDocument();
  });
});
