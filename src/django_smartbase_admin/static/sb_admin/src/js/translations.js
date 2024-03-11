class Translations {
    constructor() {
        document.querySelectorAll('.js-copy-translation').forEach(button => {
            const input = button.closest('.js-translation-field-wrapper').querySelector('input, textarea')
            const mainInputID = `id_${button.dataset.mainLang}_${input.name}`
            if(input.value) {
                return
            }
            button.removeAttribute('disabled')
            button.addEventListener('click', () => {
                if(window.CKEDITOR && window.CKEDITOR.instances[input.id]) {
                    window.CKEDITOR.instances[input.id].setData(window.CKEDITOR.instances[mainInputID].getData())
                    return
                }
                const mainInput = document.getElementById(mainInputID)
                input.value = mainInput.value
            })
        })

    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.SBAdmin = new Translations()
})