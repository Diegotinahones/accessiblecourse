export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: 'var(--color-ink)',
        subtle: 'var(--color-subtle)',
        line: 'var(--color-border)',
        panel: 'var(--color-surface-soft)',
        success: '#067647',
        warning: '#B54708',
        danger: '#B42318',
      },
      boxShadow: {
        card: '0 10px 30px rgba(16, 24, 40, 0.06)',
      },
      fontSize: {
        'display-sm': [
          '2.25rem',
          { lineHeight: '2.75rem', letterSpacing: '-0.03em' },
        ],
      },
    },
  },
  plugins: [],
};
