/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: 'var(--bg-primary)',
          secondary: 'var(--bg-secondary)',
          elevated: 'var(--bg-elevated)',
          panel: 'var(--bg-panel)',
        },
        accent: {
          cyan: 'var(--accent-cyan)',
          emerald: 'var(--accent-emerald)',
          amber: 'var(--accent-amber)',
          red: 'var(--accent-red)',
          orange: 'var(--accent-orange)',
        },
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
        },
        border: {
          subtle: 'var(--border-subtle)',
          strong: 'var(--border-strong)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': 'var(--glow-cyan)',
        'glow-emerald': 'var(--glow-emerald)',
        'glow-orange': 'var(--glow-orange)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
