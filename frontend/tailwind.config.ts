import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--bg-app) / <alpha-value>)',
        surface: {
          DEFAULT: 'hsl(var(--bg-surface) / <alpha-value>)',
          raised: 'hsl(var(--bg-surface-raised) / <alpha-value>)',
          sunken: 'hsl(var(--bg-surface-sunken) / <alpha-value>)',
        },
        border: {
          DEFAULT: 'hsl(var(--border-subtle) / <alpha-value>)',
          subtle: 'hsl(var(--border-subtle) / <alpha-value>)',
          strong: 'hsl(var(--border-strong) / <alpha-value>)',
          focus: 'hsl(var(--border-focus-hsl) / <alpha-value>)',
        },
        foreground: {
          DEFAULT: 'hsl(var(--fg-base) / <alpha-value>)',
          muted: 'hsl(var(--fg-muted) / <alpha-value>)',
          subtle: 'hsl(var(--fg-subtle) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'hsl(var(--brand-primary) / <alpha-value>)',
          hover: 'hsl(var(--brand-primary-hover) / <alpha-value>)',
          subtle: 'hsl(var(--brand-primary-subtle) / <alpha-value>)',
          foreground: 'hsl(var(--brand-primary-fg) / <alpha-value>)',
        },
        success: {
          DEFAULT: 'hsl(var(--status-success) / <alpha-value>)',
          bg: 'hsl(var(--status-success-bg) / <alpha-value>)',
          border: 'hsl(var(--status-success-border) / <alpha-value>)',
          foreground: 'hsl(var(--status-success-fg) / <alpha-value>)',
        },
        warning: {
          DEFAULT: 'hsl(var(--status-warning) / <alpha-value>)',
          bg: 'hsl(var(--status-warning-bg) / <alpha-value>)',
          border: 'hsl(var(--status-warning-border) / <alpha-value>)',
          foreground: 'hsl(var(--status-warning-fg) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'hsl(var(--status-danger) / <alpha-value>)',
          bg: 'hsl(var(--status-danger-bg) / <alpha-value>)',
          border: 'hsl(var(--status-danger-border) / <alpha-value>)',
          foreground: 'hsl(var(--status-danger-fg) / <alpha-value>)',
        },
        info: {
          DEFAULT: 'hsl(var(--status-info) / <alpha-value>)',
          bg: 'hsl(var(--status-info-bg) / <alpha-value>)',
          border: 'hsl(var(--status-info-border) / <alpha-value>)',
          foreground: 'hsl(var(--status-info-fg) / <alpha-value>)',
        },
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      boxShadow: {
        subtle: 'var(--shadow-subtle)',
        card: 'var(--shadow-card)',
        popover: 'var(--shadow-popover)',
        dialog: 'var(--shadow-dialog)',
      },
    },
  },
  plugins: [],
} satisfies Config;
