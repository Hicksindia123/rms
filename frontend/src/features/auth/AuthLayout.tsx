import { useState, type CSSProperties, type ReactNode } from 'react';
import { BadgeCheck, Boxes, ShieldCheck, Workflow } from 'lucide-react';

import hicksLogo from '@/assets/logo.png';
import { usePublicSettings } from './publicSettings';
import './login.css';

/** Shared frame for the pre-app screens (sign-in, forced password change). Branding defaults
 *  to the official Hicks India logo and company branding. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const settings = usePublicSettings();
  // Custom branding logo when configured; the URL that failed to load (if any) is remembered so
  // we fall back to the bundled Hicks logo for it, and retry if the configured URL changes.
  const [failedCustomLogo, setFailedCustomLogo] = useState<string | null>(null);
  const [logoFailed, setLogoFailed] = useState(false);
  const customLogo = settings?.branding_logo_url?.trim() || null;
  const logoSrc = customLogo && customLogo !== failedCustomLogo ? customLogo : hicksLogo;

  const style = settings
    ? ({ '--auth-brand': settings.branding_primary_color } as CSSProperties)
    : undefined;

  const appName = settings?.app_name || 'Replacement Management System';
  const companyName = settings?.company_name || 'Hicks Thermometers (India) Limited';

  const handleImageError = () => {
    if (logoSrc !== hicksLogo) {
      // If a custom URL failed, fall back to official bundled Hicks logo
      setFailedCustomLogo(logoSrc);
    } else {
      // Only if the bundled logo itself fails do we fall back to shield
      setLogoFailed(true);
    }
  };

  return (
    <div className="auth-root" style={style}>
      <aside className="auth-hero" aria-hidden="true">
        <div className="auth-hero__inner">
          <span className="auth-hero__eyebrow">{companyName}</span>
          <p className="auth-hero__title">{appName}</p>
          <p className="auth-hero__lead">
            Every returned piece tracked from the gate to the party: one place for stores,
            management and accounts.
          </p>
          <ul className="auth-hero__list">
            <li>
              <Workflow size={18} /> Guided steps for every role
            </li>
            <li>
              <Boxes size={18} /> Live stock and custody
            </li>
            <li>
              <BadgeCheck size={18} /> Management approvals with a verifiable stamp
            </li>
          </ul>
        </div>
      </aside>
      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-brand">
            <div
              className={`auth-brand__mark ${!logoFailed ? 'auth-brand__mark--logo' : ''}`}
              aria-hidden="true"
            >
              {!logoFailed ? (
                <img src={logoSrc} alt="Hicks India Limited" onError={handleImageError} />
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
