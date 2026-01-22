export default class Radio {
    constructor(selector_override, target) {
        target = target || document
        const selector = selector_override || '.js-radio-choice-widget'
        this.wrapperSelector = '.js-radio-choice-widget-wrapper'

        target.querySelectorAll(selector).forEach(el => {
            this.initRadio(el)
        })
    }

    getRadios(base_input) {
        return base_input.closest(this.wrapperSelector)?.querySelectorAll("input[type='radio']")
    }

    initRadio(base_input) {
        base_input.addEventListener('SBTableFilterFormLoad', () => {
            if (!base_input.value) {
                return
            }
            this.getRadios(base_input).forEach(el => {
                if(el.value === base_input.value) {
                    el.checked = true
                }
            })
        })
        base_input.addEventListener('clear', () => {
            base_input.closest(this.wrapperSelector)?.querySelectorAll("input[type='radio']").forEach(el => el.checked = false)
        })
    }
}
