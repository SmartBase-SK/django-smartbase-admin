import DOMPurify from 'dompurify'

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
