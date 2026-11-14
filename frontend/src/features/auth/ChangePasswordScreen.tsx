import { useState, type FormEvent } from 'react';
import { Eye, EyeOff, Loader2 } from 'lucide-react';

import { apiRequest, toApiError } from '@/lib/api/client';

import { AuthLayout } from './AuthLayout';
import { useAuth } from './useAuth';

// Mirrors the backend policy (backend/app/modules/users/schemas.py, DEC-50); the backend decides.
const MIN_LENGTH = 8;

function policyProblem(value: string): string | null {
  if (value.length < MIN_LENGTH) return `Use at least ${String(MIN_LENGTH)} characters.`;
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return 'Use at least one letter and one digit.';
  return null;
}

/** P1-05 / DEC-50: after an administrator issued a temporary password, the user sets their own
 *  password before anything else (the API answers 403 PASSWORD_CHANGE_REQUIRED until then). */
export function ChangePasswordScreen() {
  const { me, reloadMe, signOut } = useAuth();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const problem = policyProblem(password);
    if (problem) {
      setError(problem);
      return;
    }
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    setBusy(true);
    setError(null);
    apiRequest<undefined>('/me/password', { method: 'POST', body: { new_password: password } })
      .then(() => reloadMe())
      .catch((err: unknown) => {
        const apiErr = toApiError(err);
        setError(apiErr.requestId ? `${apiErr.message} (ref ${apiErr.requestId})` : apiErr.message);
        setBusy(false);
      });
  };

  return (
    <AuthLayout>
      <h1 className="auth-title">Set a new password</h1>
      <p className="auth-subtitle">
        {me?.profile.full_name ? `${me.profile.full_name}, your` : 'Your'} administrator issued a
        temporary password. Choose your own to continue.
      </p>
      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="auth-field">
          <label htmlFor="new-password" className="auth-label">
            New password
          </label>
          <div className="auth-password">
            <input
              id="new-password"
              type={show ? 'text' : 'password'}
              className="auth-input"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              disabled={busy}
              required
            />
            <button
              type="button"
              className="auth-password__toggle"
              onClick={() => {
                setShow((v) => !v);
              }}
              aria-label={show ? 'Hide password' : 'Show password'}
              aria-pressed={show}
            >
              {show ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          <p className="auth-hint">At least 8 characters, with a letter and a digit.</p>
        </div>
        <div className="auth-field">
          <label htmlFor="confirm-password" className="auth-label">
            Confirm new password
          </label>
          <input
            id="confirm-password"
            type={show ? 'text' : 'password'}
            className="auth-input"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              setError(null);
            }}
            autoComplete="new-password"
            disabled={busy}
            required
          />
        </div>
        {error && (
          <p className="auth-alert" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="auth-button" disabled={busy}>
          {busy ? (
            <>
              <Loader2 size={18} className="auth-spin" aria-hidden="true" /> Saving…
            </>
          ) : (
            'Save password'
          )}
        </button>
        <button
          type="button"
          className="auth-button auth-button--quiet"
          onClick={() => void signOut()}
          disabled={busy}
        >
          Sign out
        </button>
      </form>
    </AuthLayout>
  );
}
