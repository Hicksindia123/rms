import type { Config } from 'tailwindcss';

const BRAND = {
  50: '#eef3ff',
  100: '#dce6ff',
  200: '#bfd0ff',
  300: '#93b0ff',
  400: '#6488ff',
  500: '#3f63fb',
  600: '#2a47f0',
  700: '#2236d6',
  800: '#212fad',
  900: '#212e88',
  950: '#181d52',
};

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  corePlugins: { preflight: false },
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Plus Jakarta Sans"',
          'Inter',
          'system-ui',
          '-apple-system',
          '"Segoe UI"',
          'Roboto',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        // Brand scale (vivid royal blue). Tailwind blue + indigo both map to it, so every screen
        // using either picks up the same brand colour.
        brand: BRAND,
        blue: BRAND,
        indigo: BRAND,
        // Hicks red accent (logo colour), used sparingly.
        hicks: { 50: '#fff1f1', 100: '#ffdfdf', 500: '#ef3b33', 600: '#e2231a', 700: '#bd1a13' },
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
        glow: '0 8px 24px -6px rgba(42, 71, 240, 0.45)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.35s cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
} satisfies Config;
