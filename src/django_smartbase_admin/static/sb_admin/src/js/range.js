
export default class Range {
    constructor(selector_override, options_override, target) {
        target = target || document
        const selector = selector_override || '.js-range'
        this.separator = ' - '
        target.querySelectorAll(selector).forEach(el => {
            this.initRange(el, options_override)
        })
    }

    initRange(base_input) {
        const from_input = document.getElementById(`${base_input.id}_from`)
        const to_input = document.getElementById(`${base_input.id}_to`)
        const elems = [from_input, to_input]
        elems.forEach(el => {
            el.addEventListener('blur', () => {
                const data = {}
                if(from_input.value) {
                    data.from = {
                        value: from_input.value,
                        label: from_input.value,
                    }
                }
                if(to_input.value) {
                    data.to = {
                        value: to_input.value,
                        label: to_input.value,
                    }
                }
                base_input.value = JSON.stringify(data)
                base_input.dispatchEvent(new Event('change', {bubbles: true}))
            })
        })
        base_input.addEventListener('SBTableFilterFormLoad', () => {
            if(!base_input.value){
                return
            }
            const onLoadData = JSON.parse(base_input.value)
            from_input.value = onLoadData.from?.value
            to_input.value = onLoadData.to?.value
        })
        base_input.addEventListener('clear', () => {
            base_input.value = ""
            from_input.value = ""
            to_input.value = ""
            base_input.dispatchEvent(new Event('change'))
        })
    }
}