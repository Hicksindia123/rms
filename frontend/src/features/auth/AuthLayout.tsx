import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';

import hicksLogo from '@/assets/logo.png';
import { usePublicSettings } from './publicSettings';
import './login.css';

/** Shared frame for the pre-app screens (sign-in, forced password change). Branding defaults
 *  to the official Hicks India logo and company branding. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const settings = usePublicSettings();
  const [logoSrc, setLogoSrc] = useState<string>(hicksLogo);
  const [logoFailed, setLogoFailed] = useState(false);

  useEffect(() => {
    const custom = settings?.branding_logo_url?.trim();
    if (custom) {
      setLogoSrc(custom);
    } else {
      setLogoSrc(hicksLogo);
    }
  }, [settings?.branding_logo_url]);

  const style = settings
    ? ({ '--auth-brand': settings.branding_primary_color } as CSSProperties)
    : undefined;

  const appName = settings?.app_name || 'Replacement Management System';
  const companyName = settings?.company_name || 'Hicks Thermometers (India) Limited';

  const handleImageError = () => {
    if (logoSrc !== hicksLogo) {
      // If a custom URL failed, fall back to official bundled Hicks logo
      setLogoSrc(hicksLogo);
    } else {
      // Only if the bundled logo itself fails do we fall back to shield
      setLogoFailed(true);
    }
  };

  return (
    <div className="auth-root" style={style}>
      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-brand">
            <div
              className={`auth-brand__mark ${!logoFailed ? 'auth-brand__mark--logo' : ''}`}
              aria-hidden="true"
            >
              {!logoFailed ? (
                <img
                  src={logoSrc}
                  alt="Hicks India Limited"
                  onError={handleImageError}
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
