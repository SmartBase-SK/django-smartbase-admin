function initCodeWidget(el) {
    const options = el.getAttribute('code-mirror-options')
    const width = el.getAttribute('code-mirror-width')
    const height = el.getAttribute('code-mirror-height')
    const codeInstance = CodeMirror.fromTextArea(el, JSON.parse(options))
    codeInstance.setSize(width, height)
}

document.addEventListener('formset:added', (event) => {
    event.target.querySelectorAll('[code-mirror-options]').forEach(el => {
        initCodeWidget(el)
    })
})
