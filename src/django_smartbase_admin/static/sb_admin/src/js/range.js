import noUiSlider from "nouislider"

export default class Range {
    constructor(selector_override, options_override) {
        const selector = selector_override || '.js-range'
        document.querySelectorAll(selector).forEach(el => {
            this.initRange(el, options_override)
            //TODO: formatters
        })
    }

    initRange(el, options_override) {
        noUiSlider.create(el, this.getOptions(el, options_override))
        // min max inputs
        const minId = el.dataset['minId']
        const maxId = el.dataset['maxId']
        if(minId && maxId) {
            const inputs = [
                el.closest('.js-input-group').querySelector(`#${minId}`),
                el.closest('.js-input-group').querySelector(`#${maxId}`)
            ]
            el.noUiSlider.on('update', function (values, handle) {
                inputs[handle].value = values[handle]
            })
            inputs[0].addEventListener('change', (e)=>{
                el.noUiSlider.set([e.target.value, null])
            })
            inputs[1].addEventListener('change', (e)=>{
                el.noUiSlider.set([null, e.target.value])
            })
        }
    }

    getOptions(el, options_override) {
        return {
            connect: true,
            start: [parseFloat(el.dataset['currentMin']), parseFloat(el.dataset['currentMax'])],
            step: parseFloat(el.dataset['step']) || null,
            range: {
                'min': [parseFloat(el.dataset['min'])],
                'max': [parseFloat(el.dataset['max'])]
            },
            ...options_override
        }
    }
}