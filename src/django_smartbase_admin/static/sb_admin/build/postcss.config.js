module.exports = (api) => {
    let config = {
         plugins: {
            'postcss-import': {},
            'postcss-extend': {},
            'postcss-advanced-variables': {},
            'tailwindcss/nesting': {},
            tailwindcss: {config: '.src/django_smartbase_admin/static/sb_admin/build/tailwind.config.js'},
            'postcss-hexrgba':{},
            'postcss-automath': {},
            autoprefixer: {},
        }
    }
    if(api.mode === "production") {
        config.plugins['cssnano'] = {
            preset: 'default',
            zIndex: false
        }
    }
    return config
}