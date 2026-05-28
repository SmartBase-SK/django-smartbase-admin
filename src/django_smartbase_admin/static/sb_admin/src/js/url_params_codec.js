import LZString from 'lz-string'

const isPlainJson = (text) => {
    const stripped = text.trimStart()
    return stripped.startsWith('{') || stripped.startsWith('[')
}

export const encodeParamsForUrl = (data, compress = true) => {
    const jsonStr = JSON.stringify(data)
    if (!compress) {
        return jsonStr
    }
    return LZString.compressToEncodedURIComponent(jsonStr)
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

export const parseParamsPayload = (value) => {
    if (!value) {
        return {}
    }
    if (typeof value === 'object') {
        return value && !Array.isArray(value) ? value : {}
    }
    return decodeParamsFromUrl(value)
}
