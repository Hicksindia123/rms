import { useState, type CSSProperties, type ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';

import { usePublicSettings } from './publicSettings';
import './login.css';

/** Shared frame for the pre-app screens (sign-in, forced password change). Branding comes from
 *  the public settings (DB configuration, rule e); nothing business-specific is hard-coded. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const settings = usePublicSettings();
  const [logoFailed, setLogoFailed] = useState(false);
  const logo = settings?.branding_logo_url && !logoFailed ? settings.branding_logo_url : null;
  const style = settings
    ? ({ '--auth-brand': settings.branding_primary_color } as CSSProperties)
    : undefined;

  return (
    <div className="auth-root" style={style}>
      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand__mark" aria-hidden="true">
              {logo ? (
                <img
                  src={logo}
                  alt=""
                  onError={() => {
                    setLogoFailed(true);
                  }}
                />
              ) : (
                <ShieldCheck size={22} strokeWidth={2} />
              )}
            </div>
            <div className="auth-brand__text">
              {settings ? (
                <>
                  <span className="auth-brand__app">{settings.app_name}</span>
                  {settings.company_name && (
                    <span className="auth-brand__company">{settings.company_name}</span>
                  )}
                </>
              ) : (
                <span className="auth-skeleton" aria-hidden="true" />
              )}
            </div>
          </div>
          {children}
        </div>
      </main>
      {settings?.company_name && (
        <footer className="auth-footer">
          © {new Date().getFullYear()} {settings.company_name}
        </footer>
      )}
    </div>
  );
}
