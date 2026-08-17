const PICKER_TYPE_IMAGE = 'image'
const MODAL_SELECTOR = '#sb-admin-modal'
const EMBEDDED_PICKER_SELECTOR = '[data-sb-media-picker-embed]'
const EMBEDDED_MESSAGE_SOURCE = 'django-smartbase-admin:media-picker'
const EMBEDDED_MESSAGE_TYPES = Object.freeze({
    BUSY: 'busy',
    CANCEL: 'cancel',
    READY: 'ready',
    SELECT: 'select',
})

const pickerTranslation = (key, fallback) => (
    window.sb_admin_translation_strings?.[key] || fallback
)

const storedView = () => {
    try {
        return window.localStorage.getItem('sb-media-picker-view') || 'grid'
    } catch (error) {
        return 'grid'
    }
}

const storeView = (view) => {
    try {
        window.localStorage.setItem('sb-media-picker-view', view)
    } catch (error) {
        // Storage is optional; the picker still works without persistence.
    }
}

const widgetItem = (item) => ({
    id: Number(item.id),
    name: item.name || '',
    thumbnail_url: item.thumbnail_url || '',
})

const embeddedSelectedItem = (rootElement) => {
    try {
        const item = JSON.parse(
            rootElement.querySelector('#sb-media-picker-selected-item')?.textContent || 'null',
        )
        return item === null ? null : widgetItem(item)
    } catch (error) {
        return null
    }
}

const widgetSelectedItem = (widget) => {
    const input = widget.querySelector('.vForeignKeyRawIdAdminField')
    const id = input?.value
    if (!id) return null

    try {
        const stored = JSON.parse(widget.querySelector('script[type="application/json"]')?.textContent || 'null')
        if (String(stored?.id) === String(id)) return widgetItem(stored)
    } catch (error) {
        // A dropped file is reconstructed from django-filer's rendered preview below.
    }

    const dropzone = widget.querySelector('[data-picker-widget-dropzone]')
    const uploadedPreviews = dropzone?.querySelectorAll('[data-picker-uploaded-preview]') || []
    const uploadedPreview = uploadedPreviews[uploadedPreviews.length - 1]
    const initialPreview = widget.querySelector('[data-picker-initial-preview]')
    const image = uploadedPreview?.querySelector('[data-dz-thumbnail]')
        || initialPreview?.querySelector('[data-picker-preview-image]')
    const name = uploadedPreview?.querySelector('[data-dz-name]')?.textContent
        || initialPreview?.querySelector('[data-picker-preview-name]')?.textContent
        || ''
    return widgetItem({
        id: Number(id),
        name,
        thumbnail_url: image?.src || '',
    })
}

const updateWidget = (widget, item) => {
    if (!widget) return
    const input = widget.querySelector('.vForeignKeyRawIdAdminField')
    const dropzone = widget.querySelector('[data-picker-widget-dropzone]')
    const preview = widget.querySelector('[data-picker-initial-preview]')
    const clear = preview.querySelector('[data-picker-clear]')
    const emptyPrompt = preview.querySelector('[data-picker-empty-prompt]')
    const message = dropzone.querySelector('.js-filer-dropzone-message')
    if (dropzone.dropzone?.files.length) dropzone.dropzone.removeAllFiles(true)
    input.value = item?.id || ''
    preview.style.removeProperty('display')
    preview.querySelector('[data-picker-preview-image]').classList.toggle('hidden', !item)
    clear.classList.toggle('hidden', !item)
    emptyPrompt.classList.toggle('hidden', Boolean(item))
    message.classList.toggle('hidden', Boolean(item))
    dropzone.classList.toggle('js-object-attached', Boolean(item))
    preview.querySelector('[data-picker-preview-image]').src = item?.thumbnail_url || ''
    preview.querySelector('[data-picker-preview-name]').textContent = item?.name || ''
    widget.querySelectorAll('[data-picker-trigger-label]').forEach((label) => {
        label.textContent = item ? widget.dataset.changeLabel : widget.dataset.chooseLabel
    })
    widget.querySelector('script[type="application/json"]').textContent = JSON.stringify(item)
    input.dispatchEvent(new Event('input', {bubbles: true}))
    input.dispatchEvent(new Event('change', {bubbles: true}))
}

class MediaPicker {
    constructor({widget = null, rootElement, embedded = false}) {
        this.widget = widget
        this.rootElement = rootElement
        this.embedded = embedded
        const selectedItem = embedded
            ? embeddedSelectedItem(rootElement)
            : widgetSelectedItem(widget)
        this.selected = new Map(selectedItem ? [[String(selectedItem.id), selectedItem]] : [])
        this.view = storedView()
        this.dragDepth = 0
        this.uploading = false
        this.handleClick = this.handleClick.bind(this)
        this.handleClearSearch = this.handleClearSearch.bind(this)
        this.handleChange = this.handleChange.bind(this)
        this.handleAfterSwap = this.handleAfterSwap.bind(this)
        this.handleDragEnter = this.handleDragEnter.bind(this)
        this.handleDragOver = this.handleDragOver.bind(this)
        this.handleDragLeave = this.handleDragLeave.bind(this)
        this.handleDrop = this.handleDrop.bind(this)
        this.handleKeyDown = this.handleKeyDown.bind(this)
        this.handleHide = this.handleHide.bind(this)
        this.handleHidden = this.handleHidden.bind(this)
        this.bind()
    }

    bind() {
        this.rootElement.addEventListener('click', this.handleClearSearch, true)
        this.rootElement.addEventListener('click', this.handleClick)
        this.rootElement.addEventListener('change', this.handleChange)
        this.rootElement.addEventListener('dragenter', this.handleDragEnter)
        this.rootElement.addEventListener('dragover', this.handleDragOver)
        this.rootElement.addEventListener('dragleave', this.handleDragLeave)
        this.rootElement.addEventListener('drop', this.handleDrop)
        if (!this.embedded) {
            this.rootElement.addEventListener('hide.bs.modal', this.handleHide)
            this.rootElement.addEventListener('hidden.bs.modal', this.handleHidden)
        } else {
            this.rootElement.addEventListener('keydown', this.handleKeyDown)
        }
        document.addEventListener('htmx:afterSwap', this.handleAfterSwap)
    }

    destroy() {
        this.rootElement.removeEventListener('click', this.handleClearSearch, true)
        this.rootElement.removeEventListener('click', this.handleClick)
        this.rootElement.removeEventListener('change', this.handleChange)
        this.rootElement.removeEventListener('dragenter', this.handleDragEnter)
        this.rootElement.removeEventListener('dragover', this.handleDragOver)
        this.rootElement.removeEventListener('dragleave', this.handleDragLeave)
        this.rootElement.removeEventListener('drop', this.handleDrop)
        if (!this.embedded) {
            this.rootElement.removeEventListener('hide.bs.modal', this.handleHide)
            this.rootElement.removeEventListener('hidden.bs.modal', this.handleHidden)
        } else {
            this.rootElement.removeEventListener('keydown', this.handleKeyDown)
        }
        document.removeEventListener('htmx:afterSwap', this.handleAfterSwap)
        if (activePicker === this) activePicker = null
    }

    handleAfterSwap() {
        if (!this.embedded && !this.rootElement.classList.contains('show')) return
        this.dragDepth = 0
        window.requestAnimationFrame(() => this.syncSurface())
    }

    handleHide(event) {
        if (this.uploading) event.preventDefault()
    }

    handleHidden() {
        this.destroy()
    }

    handleKeyDown(event) {
        if (event.key !== 'Escape') return
        event.preventDefault()
        this.cancel()
    }

    handleClearSearch(event) {
        if (!event.target.closest('[data-picker-clear-search]')) return
        const search = this.rootElement.querySelector('#sb-media-picker-search')
        if (search) search.value = ''
    }

    syncSurface() {
        const surface = this.rootElement.querySelector('[data-picker-surface]')
        if (!surface) return
        const content = surface.querySelector('[data-picker-content]')
        content.classList.remove('sb-media-picker__content--grid', 'sb-media-picker__content--list')
        content.classList.add(`sb-media-picker__content--${this.view}`)
        surface.querySelectorAll('[data-picker-view]').forEach((button) => {
            button.classList.toggle('is-active', button.dataset.pickerView === this.view)
        })
        surface.querySelectorAll('[data-picker-item]').forEach((button) => {
            const selected = this.selected.has(String(button.dataset.id))
            button.classList.toggle('is-selected', selected)
            button.setAttribute('aria-pressed', selected ? 'true' : 'false')
        })
        this.updateDoneButton()
    }

    handleClick(event) {
        const cancelButton = event.target.closest('[data-picker-cancel]')
        if (cancelButton && this.embedded) {
            event.preventDefault()
            this.cancel()
            return
        }

        if (this.handleFolderMenuClick(event)) return

        const uploadButton = event.target.closest('[data-picker-upload-trigger]')
        if (uploadButton) {
            uploadButton.closest('[data-picker-surface]').querySelector('[data-picker-upload]').click()
            return
        }

        const viewButton = event.target.closest('[data-picker-view]')
        if (viewButton) {
            this.view = viewButton.dataset.pickerView
            storeView(this.view)
            this.syncSurface()
            return
        }

        const itemButton = event.target.closest('[data-picker-item]')
        if (itemButton) {
            this.toggleItem(this.itemFromButton(itemButton))
            return
        }

        if (event.target.closest('[data-picker-done]')) this.finish()
    }

    handleFolderMenuClick(event) {
        const trigger = event.target.closest('[data-picker-new-folder-trigger]')
        if (trigger) {
            const menu = trigger.closest('[data-picker-new-folder]')
            this.setFolderMenuOpen(menu, !menu.classList.contains('is-open'))
            return true
        }

        const openMenu = this.rootElement.querySelector('[data-picker-new-folder].is-open')
        if (openMenu && !event.target.closest('[data-picker-new-folder]')) {
            this.setFolderMenuOpen(openMenu, false)
        }
        return false
    }

    setFolderMenuOpen(menu, open) {
        menu.classList.toggle('is-open', open)
        menu.querySelector('[data-picker-new-folder-trigger]').setAttribute('aria-expanded', String(open))
        menu.querySelector('[data-picker-folder-form]').hidden = !open
        if (open) menu.querySelector('input[name="name"]').focus()
    }

    handleChange(event) {
        if (event.target.matches('[data-picker-upload]')) this.uploadFiles(event.target.files)
    }

    itemFromButton(button) {
        return {
            id: Number(button.dataset.id),
            name: button.dataset.name,
            thumbnail_url: button.dataset.thumbnailUrl,
        }
    }

    toggleItem(item) {
        const id = String(item.id)
        if (this.selected.has(id)) {
            this.selected.delete(id)
        } else {
            this.selected.clear()
            this.selected.set(id, item)
        }
        this.syncSurface()
    }

    updateDoneButton() {
        const button = this.rootElement.querySelector('[data-picker-done]')
        if (button) button.disabled = this.selected.size === 0
    }

    uploadUrl() {
        return this.rootElement.querySelector('[data-picker-upload-url]')?.dataset.pickerUploadUrl
    }

    maxUploadFiles() {
        const value = Number.parseInt(
            this.rootElement.querySelector('[data-picker-upload-url]')?.dataset.pickerUploadMaxFiles,
            10,
        )
        return Number.isNaN(value) ? null : Math.max(0, value)
    }

    maxUploadFileSize() {
        const value = Number.parseFloat(
            this.rootElement.querySelector('[data-picker-upload-url]')?.dataset.pickerUploadMaxFileSize,
        )
        return Number.isNaN(value) || value <= 0 ? null : value
    }

    hasDraggedFiles(event) {
        return Array.from(event.dataTransfer?.types || []).includes('Files')
    }

    setDropzoneActive(active) {
        this.rootElement.querySelector('[data-picker-surface]')?.classList.toggle('is-dragging', active)
    }

    handleDragEnter(event) {
        if (!this.uploadUrl() || !this.hasDraggedFiles(event)) return
        event.preventDefault()
        this.dragDepth += 1
        this.setDropzoneActive(true)
    }

    handleDragOver(event) {
        if (!this.uploadUrl() || !this.hasDraggedFiles(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
    }

    handleDragLeave(event) {
        if (!this.uploadUrl() || !this.hasDraggedFiles(event)) return
        event.preventDefault()
        this.dragDepth = Math.max(0, this.dragDepth - 1)
        if (this.dragDepth === 0) this.setDropzoneActive(false)
    }

    handleDrop(event) {
        if (!this.uploadUrl() || !this.hasDraggedFiles(event)) return
        event.preventDefault()
        this.dragDepth = 0
        this.setDropzoneActive(false)
        this.uploadFiles(event.dataTransfer.files)
    }

    setUploadProgress(current, total, percent = 0) {
        const loading = this.rootElement.querySelector('[data-picker-loading]')
        if (!loading) return
        loading.querySelector('[data-picker-loading-text]').textContent =
            `${loading.dataset.uploadingLabel} ${current}/${total} (${percent}%)`
        loading.classList.add('is-uploading')
    }

    clearUploadProgress() {
        const loading = this.rootElement.querySelector('[data-picker-loading]')
        if (!loading) return
        loading.classList.remove('is-uploading')
        loading.querySelector('[data-picker-loading-text]').textContent = loading.dataset.loadingLabel
    }

    waitForPaint() {
        return new Promise((resolve) => {
            window.requestAnimationFrame(() => window.requestAnimationFrame(resolve))
        })
    }

    uploadFile(file, uploadUrl, onProgress) {
        return new Promise((resolve, reject) => {
            const request = new XMLHttpRequest()
            request.open('POST', uploadUrl)
            request.upload.addEventListener('progress', (event) => {
                if (!event.lengthComputable) return
                const percent = Math.round((event.loaded / event.total) * 100)
                onProgress(Math.min(100, Math.max(0, percent)))
            })
            request.addEventListener('load', () => {
                let data
                try {
                    data = JSON.parse(request.responseText)
                } catch (error) {
                    reject(new Error(`${request.status}`))
                    return
                }
                if (request.status < 200 || request.status >= 300 || data.error) {
                    reject(new Error(data.error || `${request.status}`))
                    return
                }
                resolve(data)
            })
            request.addEventListener('error', () => {
                reject(new Error(pickerTranslation('media_picker_error', 'Error:')))
            })

            const body = new FormData()
            body.append('file', file)
            request.send(body)
        })
    }

    async uploadFiles(fileList) {
        const pickerType = this.rootElement.querySelector('[data-picker-surface]')?.dataset.pickerType
        const mediaFiles = Array.from(fileList || []).filter(
            (file) => pickerType !== PICKER_TYPE_IMAGE || file.type.startsWith('image/'),
        )
        const maxFileSize = this.maxUploadFileSize()
        const maxFileSizeBytes = maxFileSize === null ? null : maxFileSize * 1024 * 1024
        const oversizedFiles = maxFileSizeBytes === null
            ? []
            : mediaFiles.filter((file) => file.size > maxFileSizeBytes)
        const eligibleFiles = maxFileSizeBytes === null
            ? mediaFiles
            : mediaFiles.filter((file) => file.size <= maxFileSizeBytes)
        const maxFiles = this.maxUploadFiles()
        const files = maxFiles === null ? eligibleFiles : eligibleFiles.slice(0, maxFiles)
        const uploadUrl = this.uploadUrl()
        const sizeError = oversizedFiles.length
            ? `${pickerTranslation('media_picker_error', 'Error:')} ${
                oversizedFiles.map((file) => file.name).join(', ')
            } > ${maxFileSize} MB`
            : ''
        if (!files.length || !uploadUrl || this.uploading) {
            if (sizeError && uploadUrl && !this.uploading) {
                this.rootElement.querySelector('[data-picker-status]').textContent = sizeError
            }
            const input = this.rootElement.querySelector('[data-picker-upload]')
            if (input) input.value = ''
            return
        }

        this.setUploading(true)
        this.rootElement.querySelector('[data-picker-status]').textContent = ''
        this.setUploadProgress(1, files.length, 0)
        await this.waitForPaint()
        try {
            for (const [index, file] of files.entries()) {
                this.setUploadProgress(index + 1, files.length, 0)
                await this.uploadFile(file, uploadUrl, (percent) => {
                    this.setUploadProgress(index + 1, files.length, percent)
                })
                this.setUploadProgress(index + 1, files.length, 100)
            }
            await this.refreshSurface()
            if (sizeError) {
                this.rootElement.querySelector('[data-picker-status]').textContent = sizeError
            }
        } catch (error) {
            this.rootElement.querySelector('[data-picker-status]').textContent = error.message || String(error)
        } finally {
            this.setUploading(false)
            this.clearUploadProgress()
            const input = this.rootElement.querySelector('[data-picker-upload]')
            if (input) input.value = ''
        }
    }

    refreshSurface() {
        const surface = this.rootElement.querySelector('[data-picker-surface]')
        const filters = surface.querySelector('[data-picker-filters]')
        const url = new URL(surface.dataset.endpoint, window.location.href)
        new FormData(filters).forEach((value, key) => url.searchParams.set(key, value))
        return window.htmx.ajax('GET', url.toString(), {
            target: surface,
            select: '[data-picker-surface]',
            swap: 'outerHTML',
        })
    }

    setUploading(uploading) {
        this.uploading = uploading
        if (this.embedded) {
            this.postEmbeddedMessage(EMBEDDED_MESSAGE_TYPES.BUSY, {busy: uploading})
        }
    }

    postEmbeddedMessage(type, detail = {}) {
        window.parent.postMessage({
            source: EMBEDDED_MESSAGE_SOURCE,
            type,
            requestId: this.rootElement.dataset.pickerRequestId,
            ...detail,
        }, window.location.origin)
    }

    cancel() {
        if (!this.uploading) this.postEmbeddedMessage(EMBEDDED_MESSAGE_TYPES.CANCEL)
    }

    finish() {
        const item = Array.from(this.selected.values())[0]
        if (!item) return
        if (this.embedded) {
            const pickerType = this.rootElement.querySelector('[data-picker-surface]').dataset.pickerType
            this.postEmbeddedMessage(EMBEDDED_MESSAGE_TYPES.SELECT, {
                item: {
                    ...item,
                    reference: `filer://${pickerType}/${item.id}`,
                },
            })
            return
        }
        updateWidget(this.widget, item)
        window.bootstrap5.Modal.getInstance(this.rootElement)?.hide()
    }
}

let activePicker = null

const initializePicker = (widget) => {
    const rootElement = document.querySelector(MODAL_SELECTOR)
    if (!widget || !rootElement) return
    activePicker?.destroy()
    activePicker = new MediaPicker({widget, rootElement})
}

const initializeEmbeddedPicker = () => {
    const rootElement = document.querySelector(EMBEDDED_PICKER_SELECTOR)
    if (!rootElement) return
    activePicker?.destroy()
    activePicker = new MediaPicker({rootElement, embedded: true})
    activePicker.syncSurface()
    activePicker.postEmbeddedMessage(EMBEDDED_MESSAGE_TYPES.READY)
}

document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-sb-media-picker-trigger]')
    if (trigger) initializePicker(trigger.closest('[data-sb-media-picker-widget]'))

    const clear = event.target.closest('[data-picker-clear]')
    if (clear) updateWidget(clear.closest('[data-sb-media-picker-widget]'), null)
}, true)

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeEmbeddedPicker, {once: true})
} else {
    initializeEmbeddedPicker()
}
