const defaultFontStack = ', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"';

module.exports = {
    fontFamily: {
        'heading': 'Inter' + defaultFontStack,
        'body': 'Inter' + defaultFontStack,
    },
    fontSize: {
        '12': ['0.75rem', '1.25rem'],
        '14': ['0.875rem', '1.25rem'],
        '16': ['1rem', '1.25rem'],
        '18': ['1.125rem', '1.25rem'],
        '24': ['1.5rem', '2rem'],
        '30': ['1.875rem', '2.75rem'],
    },
    lineHeight: {
        none: '1',
        tight: '1.25',
        snug: '1.375',
        normal: '1.5',
        relaxed: '1.625',
        loose: '2',
        14: '0.875rem',
        16: '1rem',
        18: '1.125rem',
        20: '1.25rem',
        24: '1.5rem',
        28: '1.75rem',
    },
}