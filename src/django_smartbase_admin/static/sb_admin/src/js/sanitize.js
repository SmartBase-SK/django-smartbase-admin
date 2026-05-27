import DOMPurify from 'dompurify'

// SBAdmin sprite icons: <svg><use xlink:href="#Icon"></use></svg>
DOMPurify.setConfig({
    ADD_TAGS: ['use'],
    ADD_ATTR: ['xlink:href', 'href'],
})

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName !== 'use') {
        return
    }
    for (const attr of ['xlink:href', 'href']) {
        const value = node.getAttribute(attr)
        if (value && !value.startsWith('#')) {
            node.removeAttribute(attr)
        }
    }
})

// Single sink wrapper: every place that previously wrote untrusted strings
// to `innerHTML` / jQuery `.html()` should route through `sanitizeHtml` so
// reflected payloads (URL filterData labels, autocomplete responses, page
// size, tree column values, ...) cannot break out of an attribute or fire
// `<script>` / `onerror` handlers. Server-trusted markup from `label_lambda`
// (badges, icons) survives because DOMPurify keeps a safe HTML subset.
export const sanitizeHtml = (value) => {
    if (value === null || value === undefined) {
        return ''
    }
    return DOMPurify.sanitize(String(value))
}
