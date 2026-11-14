import { useState, type FormEvent } from 'react';
import { ArrowRight, Eye, EyeOff, Loader2 } from 'lucide-react';

import { useAuth } from '@/features/auth/useAuth';

import { AuthLayout } from './AuthLayout';

interface LoginFormProps {
  onSuccess?: () => void;
}

// Local-development convenience only (production audit 2026-11-14). `import.meta.env.DEV` is a
// build-time constant: in `vite build` it is false, so the accounts and the shared UAT password
// are removed from the production bundle and the picker is not rendered.
const UAT_QUICK_FILL = import.meta.env.DEV;
const DEV_ACCOUNTS: Array<{ label: string; email: string }> = !UAT_QUICK_FILL
  ? []
  : [
      { label: 'Super Admin', email: 'admin@rms.local' },
      { label: 'Replacement Manager', email: 'pratham@rms.local' },
      { label: 'Inward Verifier', email: 'aman@rms.local' },
      { label: 'Gate Security', email: 'anuj@rms.local' },
      { label: 'Accounts', email: 'deepak@rms.local' },
      { label: 'Technician', email: 'rajkumar@rms.local' },
      { label: 'Dispatch', email: 'dispatch@rms.local' },
    ];
const DEV_PASSWORD = UAT_QUICK_FILL ? 'Uat@2026RMS!' : '';

function friendlyError(message: string): string {
  const lowered = message.toLowerCase();
  if (lowered.includes('failed to fetch') || lowered.includes('network')) {
    return import.meta.env.DEV
      ? 'Cannot reach the local sign-in service (127.0.0.1:54321). Start Docker Desktop and run "supabase start".'
      : 'Cannot reach the sign-in service. Check your connection and try again.';
  }
  if (lowered.includes('invalid login credentials')) {
    return 'The email or password is incorrect.';
  }
  return message;
}

export function LoginForm({ onSuccess }: LoginFormProps) {
  const { signIn, signOut, status, me, session, error: authError } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Enter your email and password.');
      return;
    }
    setError(null);
    setLoading(true);
    signIn(email.trim(), password)
      .then(() => {
        setPassword('');
        onSuccess?.();
      })
      .catch((err: unknown) => {
        setError(friendlyError(err instanceof Error ? err.message : String(err)));
      })
      .finally(() => {
        setLoading(false);
      });
  };

  // Signed in with Supabase, but the RMS profile could not be loaded (e.g. account inactive).
  if (status === 'error' && session) {
    return (
      <AuthLayout>
        <h1 className="auth-title">Unable to continue</h1>
        <p className="auth-alert" role="alert">
          {authError ?? 'Your account could not be loaded.'}
        </p>
        <button type="button" className="auth-button" onClick={() => void signOut()}>
          Sign out
        </button>
      </AuthLayout>
    );
  }

  if (status === 'signed-in' && me) {
    return (
      <AuthLayout>
        <h1 className="auth-title">Welcome back</h1>
        <p className="auth-subtitle">
          Signed in as <strong>{me.profile.full_name}</strong>
        </p>
        <button type="button" className="auth-button" onClick={() => onSuccess?.()}>
          Continue <ArrowRight size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="auth-button auth-button--quiet"
          onClick={() => void signOut()}
        >
          Sign out
        </button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <h1 className="auth-title">Sign in</h1>
      <p className="auth-subtitle">Use your work email and password.</p>

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="auth-field">
          <label htmlFor="login-email" className="auth-label">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            className="auth-input"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError(null);
            }}
            autoComplete="username"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            required
            disabled={loading}
          />
        </div>

        <div className="auth-field">
          <label htmlFor="login-password" className="auth-label">
            Password
          </label>
          <div className="auth-password">
            <input
              id="login-password"
              type={showPassword ? 'text' : 'password'}
              className="auth-input"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError(null);
              }}
              autoComplete="current-password"
              required
              disabled={loading}
            />
            <button
              type="button"
              className="auth-password__toggle rms-pwd-toggle"
              onClick={() => {
                setShowPassword((v) => !v);
              }}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>

        {error && (
          <p className="auth-alert" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="auth-button" disabled={loading}>
          {loading ? (
            <>
              <Loader2 size={18} className="auth-spin" aria-hidden="true" /> Signing in…
            </>
          ) : (
            'Sign in'
          )}
        </button>
      </form>

      <p className="auth-note">Forgot your password? Contact your administrator.</p>

      {UAT_QUICK_FILL && (
        <label className="auth-dev">
          <span>Development only: fill a test account</span>
          <select
            value=""
            onChange={(e) => {
              if (!e.target.value) return;
              setEmail(e.target.value);
              setPassword(DEV_PASSWORD);
              setError(null);
            }}
          >
            <option value="">Choose…</option>
            {DEV_ACCOUNTS.map((a) => (
              <option key={a.email} value={a.email}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
      )}
    </AuthLayout>
  );
}
