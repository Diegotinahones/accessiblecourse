export default {
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            colors: {
                ink: '#101828',
                subtle: '#475467',
                line: '#D0D5DD',
                panel: '#F8FAFC',
                success: '#067647',
                warning: '#B54708',
                danger: '#B42318',
            },
            boxShadow: {
                card: '0 10px 30px rgba(16, 24, 40, 0.06)',
            },
            fontSize: {
                'display-sm': ['2.25rem', { lineHeight: '2.75rem', letterSpacing: '-0.03em' }],
            },
        },
    },
    plugins: [],
};
