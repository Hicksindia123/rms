import type { Config } from 'tailwindcss';

/**
 * Tailwind CSS (master plan §7 / §6.3, P1-04). Added in P3-08: screens built since P2-06 use
 * utility classes, but Tailwind was never installed, so they rendered unstyled.
 *
 * - `preflight: false`: the hand-written design system in src/styles/index.css keeps its own
 *   base styles; Tailwind only contributes utilities, so existing screens are unaffected.
 * - `darkMode: 'class'`: the app has no dark theme yet (no `.dark` class is ever set), so `dark:`
 *   variants stay inert instead of following the OS setting on a few screens only.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  corePlugins: { preflight: false },
  theme: { extend: {} },
  plugins: [],
} satisfies Config;
