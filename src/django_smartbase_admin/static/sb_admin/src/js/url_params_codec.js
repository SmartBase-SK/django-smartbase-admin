import LZString from 'lz-string'

const isPlainJson = (text) => {
    const stripped = text.trimStart()
    return stripped.startsWith('{') || stripped.startsWith('[')
}

export const encodeParamsForUrl = (data) => {
    return LZString.compressToEncodedURIComponent(JSON.stringify(data))
}

export const decodeParamsFromUrl = (value) => {
    if (!value) {
        return {}
    }
    try {
        const raw = isPlainJson(value)
            ? value
            : LZString.decompressFromEncodedURIComponent(value)
        if (!raw) {
            return {}
        }
        const data = JSON.parse(raw)
        return data && typeof data === 'object' && !Array.isArray(data) ? data : {}
    } catch (e) {
        return {}
    }
}
