const media = JSON.parse(document.getElementById('sb-admin-modal-media').textContent)

function resolveUrl(relativePath) {
    const a = document.createElement('a')
    a.href = window.sb_admin_const.STATIC_URL + relativePath
    return a.href
}

const existingScripts = new Set(
    Array.from(document.querySelectorAll('script[src]')).map(function (el) { return el.src })
)
const existingStyles = new Set(
    Array.from(document.querySelectorAll('link[rel="stylesheet"][href]')).map(function (el) { return el.href })
)

var scriptsToLoad = (media.js || []).reduce(function (acc, path) {
    var url = resolveUrl(path)
    if (!existingScripts.has(url.toString())) {
        acc.push(url)
    }
    return acc
}, [])

console.log(scriptsToLoad)

Object.entries(media.css || {}).forEach(function ([medium, paths]) {
    paths.forEach(function (path) {
        var url = resolveUrl(path)
        if (!existingStyles.has(url.toString())) {
            var link = document.createElement('link')
            link.rel = 'stylesheet'
            link.media = medium
            link.href = url
            document.head.appendChild(link)
        }
    })
})

function loadScriptSequentially(urls, index) {
    window.modalMediaLoaded = false
    if (index >= urls.length) {
        const loaded = function() {
            window.modalMediaLoaded = true
            document.removeEventListener('modalMediaLoaded',loaded)
        }
        document.addEventListener('modalMediaLoaded',loaded)
        document.dispatchEvent(new Event('modalMediaLoaded'))
        return
    }
    var script = document.createElement('script')
    script.src = urls[index]
    script.onload = function () { loadScriptSequentially(urls, index + 1) }
    script.onerror = function () { loadScriptSequentially(urls, index + 1) }
    document.head.appendChild(script)
}

loadScriptSequentially(scriptsToLoad, 0)