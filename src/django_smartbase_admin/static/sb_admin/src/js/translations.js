class Translations {
    constructor() {
        document.querySelectorAll('.js-copy-translation').forEach(button => {
            const input = button.closest('.js-translation-field-wrapper').querySelector('input, textarea')
            const mainInputID = `id_${button.dataset.mainLang}_${input.name}`
            const mainInput = document.getElementById(mainInputID)
            if(input.value || !mainInput?.value) {
                return
            }
            button.removeAttribute('disabled')
            button.addEventListener('click', () => {
                if(window.CKEDITOR && window.CKEDITOR.instances[input.id]) {
                    window.CKEDITOR.instances[input.id].setData(window.CKEDITOR.instances[mainInputID].getData())
                    return
                }
                const targetPicker = input.closest('[data-sb-media-picker-widget]')
                const mainPicker = mainInput.closest('[data-sb-media-picker-widget]')
                if(targetPicker && mainPicker) {
                    const item = JSON.parse(
                        mainPicker.querySelector('script[type="application/json"]').textContent,
                    )
                    targetPicker.dispatchEvent(new CustomEvent('sbadmin:media-picker:set-value', {
                        bubbles: true,
                        detail: {item},
                    }))
                    return
                }
                input.value = mainInput.value
                input.dispatchEvent(new Event('input', {bubbles: true}))
                input.dispatchEvent(new Event('change', {bubbles: true}))
            })
        })

    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.SBAdmin = new Translations()
})
