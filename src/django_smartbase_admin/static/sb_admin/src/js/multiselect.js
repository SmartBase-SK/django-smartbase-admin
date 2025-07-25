import {setDropdownLabel} from "./utils"

export default class Multiselect {
    constructor(selector_override, options_override, target) {
        target = target || document
        const selector = selector_override || '.js-simple-multiselect'
        const selectorDetail = '.js-simple-multiselect-detail'
        const selectAllClass = 'js-simple-multiselect-all'
        this.wrapperSelector = '.js-simple-multiselect-wrapper'
        if(target === document) {
            document.addEventListener('change', e => {
                const wrapperEl = e.target.closest(this.wrapperSelector)
                const multiselectInput = wrapperEl?.querySelector(selector)
                if(!wrapperEl || !multiselectInput) {
                    // not filter widget
                    return
                }
                const isCheckboxClicked = e.target.type === 'checkbox'
                const selectAllEl = wrapperEl?.querySelector(`.${selectAllClass}`)
                if(isCheckboxClicked) {
                    const checkboxes = Array.from(this.getCheckboxes(multiselectInput))
                    if(e.target.classList.contains(selectAllClass)) {
                        checkboxes.forEach(el => {
                            el.checked = e.target.checked
                        })
                    } else {
                        if(selectAllEl) {
                            selectAllEl.checked = false
                        }
                    }
                    if(selectAllEl && !checkboxes.some(el => el.checked)) {
                        selectAllEl.checked = true
                    }
                    let checked = []
                    checkboxes.forEach(el => {
                        if(el.checked) {
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
            document.addEventListener('formset:added', (event) => {
                event.target.querySelectorAll(selectorDetail).forEach(el => {
                    this.initDetailMultiselect(el)
                })
            })
        }
        target.querySelectorAll(selector).forEach(el => {
            this.initMultiselect(el, options_override)
        })
        target.querySelectorAll(selectorDetail).forEach(el => {
            this.initDetailMultiselect(el)
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

    clearAll(wrapper, valueEl) {
        wrapper.querySelectorAll('input[type="checkbox"]').forEach(el => {
            el.checked = false
        })
        setDropdownLabel(wrapper, valueEl)
    }


    initDetailMultiselect(wrapper) {
        const clearEl = wrapper.querySelector('.js-clear')

        clearEl?.addEventListener('click', () => {
            this.clearAll(wrapper)
        })
        setDropdownLabel(wrapper)
    }
}