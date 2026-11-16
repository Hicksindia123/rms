import { useState, type CSSProperties, type ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';

import { usePublicSettings } from './publicSettings';
import './login.css';

/** Shared frame for the pre-app screens (sign-in, forced password change). Branding comes from
 *  the public settings (DB configuration, rule e); nothing business-specific is hard-coded. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const settings = usePublicSettings();
  const [logoFailed, setLogoFailed] = useState(false);
  const logo = !logoFailed ? (settings?.branding_logo_url ?? '/assets/logo.png') : null;
  const style = settings
    ? ({ '--auth-brand': settings.branding_primary_color } as CSSProperties)
    : undefined;

  const appName = settings?.app_name ?? 'Replacement Management System';
  const companyName = settings?.company_name ?? 'Hicks India Limited';

  return (
    <div className="auth-root" style={style}>
      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-brand">
            <div
              className={`auth-brand__mark ${logo ? 'auth-brand__mark--logo' : ''}`}
              aria-hidden="true"
            >
              {logo ? (
                <img
                  src={logo}
                  alt="Hicks India Logo"
                  onError={() => {
                    setLogoFailed(true);
                  }}
                />
              ) : (
                <ShieldCheck size={22} strokeWidth={2} />
              )}
            </div>
            <div className="auth-brand__text">
              <span className="auth-brand__app">{appName}</span>
              <span className="auth-brand__company">{companyName}</span>
            </div>
          </div>
          {children}
        </div>
      </main>
      <footer className="auth-footer">
        © {new Date().getFullYear()} {companyName}
      </footer>
    </div>
  );
}
