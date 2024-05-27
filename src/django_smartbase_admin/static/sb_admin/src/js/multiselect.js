export default class Multiselect {
    constructor(selector_override, options_override) {
        const selector = selector_override || '.js-simple-multiselect'
        const selectorDetail = '.js-simple-multiselect-detail'
        this.wrapperSelector = '.js-simple-multiselect-wrapper'
        document.addEventListener('change', e => {
            const wrapperEl = e.target.closest(this.wrapperSelector)
            const multiselectInput = wrapperEl?.querySelector(selector)
            const changedCheckbox = wrapperEl?.querySelector('[type="checkbox"]')
            if (multiselectInput && changedCheckbox) {
                let checked = []
                this.getCheckboxes(multiselectInput).forEach(el => {
                    if (el.checked) {
                        checked.push({
                            value: el.value,
                            label: el.dataset.label,
                        })
                    }
                })
                multiselectInput.value = JSON.stringify(checked)
                multiselectInput.dispatchEvent(new Event('change', {bubbles: true}))
            }
        })
        document.querySelectorAll(selector).forEach(el => {
            this.initMultiselect(el, options_override)
        })
        document.querySelectorAll(selectorDetail).forEach(el => {
            this.initDetailMultiselect(el)
        })
        document.addEventListener('formset:added', (event) => {
            event.target.querySelectorAll(selectorDetail).forEach(el => {
                this.initDetailMultiselect(el)
            })
        })
    }

    getCheckboxes(base_input) {
        return base_input.closest(this.wrapperSelector)?.querySelectorAll("input[type='checkbox']")
    }

    initMultiselect(base_input) {
        base_input.addEventListener('SBTableFilterFormLoad', () => {
            if (!base_input.value) {
                return
            }
            let checkedCheckboxes = []
            try {
                checkedCheckboxes = JSON.parse(base_input.value).map(el => el.value)
            } catch (e) { /* empty */
            }
            this.getCheckboxes(base_input).forEach(el => {
                if (checkedCheckboxes.includes(el.value)) {
                    el.checked = true
                }
            })

        })
        base_input.addEventListener('clear', () => {
            base_input.closest(this.wrapperSelector)?.querySelectorAll("input[type='checkbox']").forEach(el => el.checked = false)
            base_input.dispatchEvent(new Event('change'))
        })
    }


    setLabel(wrapper, valueEl) {
        let labels = []
        wrapper.querySelectorAll('input[type="checkbox"]').forEach(el => {
            if (el.checked) {
                labels.push(document.querySelector(`label[for="${el.id}"]`).innerText)
            }
        })
        valueEl.innerHTML = labels.join(',')
    }

    clearAll(wrapper, valueEl) {
        wrapper.querySelectorAll('input[type="checkbox"]').forEach(el => {
            el.checked = false
        })
        this.setLabel(wrapper, valueEl)
    }


    initDetailMultiselect(wrapper) {
        const valueEl = wrapper.querySelector('.js-value')
        const clearEl = wrapper.querySelector('.js-clear')

        wrapper.addEventListener('change', () => {
            this.setLabel(wrapper, valueEl)
        })
        clearEl?.addEventListener('click', () => {
            this.clearAll(wrapper, valueEl)
        })
        this.setLabel(wrapper, valueEl)
    }
}