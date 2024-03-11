const screens = require('./tailwind_config_partials/screens')
const colors = require('./tailwind_config_partials/colors')
const spacing = require('./tailwind_config_partials/spacing')
const typography = require('./tailwind_config_partials/typography')

module.exports = {
    content: [
        '.src/django_smartbase_admin/templates/**/*.html',
        '.src/django_smartbase_admin/static/sb_admin/src/js/**/*.js',
    ],
    corePlugins: {
        container: false,
    },
    theme: {
        ...screens,
        ...colors,
        ...spacing,
        ...typography,
        borderRadius: {
            'none': '0px',
            'xs': '2px',
            'sm': '4px',
            DEFAULT: '6px',
            'lg': '8px',
            'full': '9999px'
        },
        boxShadow: {
            'inset-xs': 'inset 0 2px 2px 0 rgb(0 0 0 / 0.10)',
            xs: '0 1px 2px 0 rgb(0 0 0 / 0.10)',
            s: '0 2px 4px 0 rgb(0 0 0 / 0.10)',
            DEFAULT: '0 4px 16px 0 rgb(0 0 0 / 0.10)',
            l: '0 8 24px 0px rgb(0 0 0 / 0.10)',
            none: 'none',
            nav: '0px -4px 16px 0px rgba(17, 24, 39, 0.08)',
            focus: '0px 0px 0px 2px #FFFFFF, 0px 0px 0px 4px #009FA7'
        },
        container: {
            sm: '540px',
            md: '720px',
            lg: '960px',
            xl: '1152px',
            '2xl': '1152px',
        },
        disabledPlugins: [],
        extend: {
            keyframes: {
                rotate: {
                    '0%': {transform: 'rotate(0deg)'},
                    '100%': {transform: 'rotate(360deg)'},
                }
            },
            animation: {
                rotate: 'rotate 1s linear infinite',
            },
            transitionProperty: {
                'width': 'width',
                'height': 'height',
                'bullets': 'padding, width, opacity',
            },
            backdropBlur: {
                sm: '4px',
            },
            zIndex: {
                '1': 1,
                '1000': 1000
            },
            width: {
                '120': '7.5rem',
                '176': '11rem',
                '1/3': '33.333334%', //fixed default tailwind value
                '2/3': '66.666667%' //fixed default tailwind value
            },
        },
    },
    plugins: [
        require('@tailwindcss/line-clamp'),
    ]
}
