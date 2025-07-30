// values of css variables are defined in _colors.css
const colors = ['dark', 'primary', 'secondary', 'success', 'warning', 'negative', 'notice']
const alphaColors = ['dark'] // colors for which we want to generate alpha values
const shades = [50, 100, 200, 300, 400, 'DEFAULT', 600, 700, 800, 900]

const createColorConfig = () => {
    let result = {}
    colors.forEach(color => {
        result[color] = {}
        shades.forEach(shade => {
            if(shade === "DEFAULT") {
                result[color][shade] = `var(--color-${color})`
                return
            }
            result[color][shade] = `var(--color-${color}-${shade})`
        })
        if(alphaColors.includes(color)) {
            result[color]['a'] = `rgb(var(--color-${color}-a) / <alpha-value>)`
        }
    })
    return result
}

module.exports = {
    colors: {
        current: 'currentColor',
        light: 'var(--color-light)',
        'light-a': 'rgb(var(--color-light-a) / <alpha-value>)',
        'transparent': 'var(--color-transparent)',
        ...createColorConfig(),
        'bg': 'var(--color-bg)',
        'bg-elevated': 'var(--color-bg-elevated)',
        'bg-input': 'var(--color-bg-input)',
    }
}