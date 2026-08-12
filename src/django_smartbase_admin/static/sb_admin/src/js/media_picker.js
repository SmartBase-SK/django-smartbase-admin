// Public API: SBMediaPicker.open({endpoint, selected, multiple, origin, onSelect}).
// Runtime dependency: HTMX. Styles are self-contained in media_picker_style.css.
// The server renders the picker; this controller owns only transient browser state.
const PICKER_TYPE_IMAGE = 'image'

const dispatchPickerEvent = (target, name, detail) => {
    target.dispatchEvent(new CustomEvent(name, {detail, bubbles: true}))
}

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

class MediaPicker {
    constructor(options) {
        this.options = options
        this.origin = options.origin || document
        this.multiple = Boolean(options.multiple)
        this.selected = new Map((options.selected || []).map((item) => [String(item.id), item]))
        this.view = storedView()
        this.dragDepth = 0
        this.uploading = false
        this.pointerDownOnBackdrop = false
        this.restoreFocus = document.activeElement
        this.handleClick = this.handleClick.bind(this)
        this.handlePointerDown = this.handlePointerDown.bind(this)
        this.handleClearSearch = this.handleClearSearch.bind(this)
        this.handleChange = this.handleChange.bind(this)
        this.handleAfterSwap = this.handleAfterSwap.bind(this)
        this.handleDragEnter = this.handleDragEnter.bind(this)
        this.handleDragOver = this.handleDragOver.bind(this)
        this.handleDragLeave = this.handleDragLeave.bind(this)
        this.handleDrop = this.handleDrop.bind(this)
        this.handleKeyDown = this.handleKeyDown.bind(this)
        this.createDialog()
    }

    createDialog() {
        this.dialog = document.createElement('dialog')
        this.dialog.className = 'sb-media-picker'
        this.dialog.setAttribute('aria-labelledby', 'sb-media-picker-title')
        this.dialog.append(this.createInitialLoading())
        this.dialog.addEventListener('pointerdown', this.handlePointerDown)
        this.dialog.addEventListener('click', this.handleClearSearch, true)
        this.dialog.addEventListener('click', this.handleClick)
        this.dialog.addEventListener('change', this.handleChange)
        this.dialog.addEventListener('cancel', (event) => {
            if (event.target !== this.dialog) return
            event.preventDefault()
            if (!this.uploading) this.close(true)
        })
        this.dialog.addEventListener('dragenter', this.handleDragEnter)
        this.dialog.addEventListener('dragover', this.handleDragOver)
        this.dialog.addEventListener('dragleave', this.handleDragLeave)
        this.dialog.addEventListener('drop', this.handleDrop)
        document.addEventListener('htmx:afterSwap', this.handleAfterSwap)
        document.addEventListener('keydown', this.handleKeyDown, true)
        document.body.append(this.dialog)
        document.body.classList.add('sb-media-picker-open')
        this.dialog.showModal()
        dispatchPickerEvent(this.origin, 'sb-media-picker:open', {picker: this})

        const url = new URL(this.options.endpoint, window.location.href)
        if (this.options.folder) url.searchParams.set('folder', this.options.folder)
        window.htmx.ajax('GET', url.toString(), {target: this.dialog, swap: 'innerHTML'})
    }

    createInitialLoading() {
        const loading = document.createElement('div')
        loading.className = 'sb-media-picker__loading is-loading'
        loading.setAttribute('role', 'status')
        loading.setAttribute('aria-live', 'polite')

        const message = document.createElement('span')
        message.className = 'sb-media-picker__loading-message'

        const spinner = document.createElement('span')
        spinner.className = 'sb-media-picker__spinner'
        spinner.setAttribute('aria-hidden', 'true')

        const label = document.createElement('span')
        label.textContent = pickerTranslation('media_picker_loading', 'Loading...')
        message.append(spinner, label)
        loading.append(message)
        return loading
    }

    handleAfterSwap() {
        if (!this.dialog.open) return
        this.dragDepth = 0
        window.requestAnimationFrame(() => this.syncSurface())
    }

    handleKeyDown(event) {
        if (event.key !== 'Escape' || !this.uploading || !this.dialog.open) return
        event.preventDefault()
        event.stopImmediatePropagation()
    }

    handleClearSearch(event) {
        if (!event.target.closest('[data-picker-clear-search]')) return
        const search = this.dialog.querySelector('#sb-media-picker-search')
        if (search) search.value = ''
    }

    isOutsideDialog(clientX, clientY) {
        const bounds = this.dialog.getBoundingClientRect()
        return clientX < bounds.left
            || clientX > bounds.right
            || clientY < bounds.top
            || clientY > bounds.bottom
    }

    handlePointerDown(event) {
        this.pointerDownOnBackdrop = event.target === this.dialog
            && this.isOutsideDialog(event.clientX, event.clientY)
    }

    syncSurface() {
        const surface = this.dialog.querySelector('[data-picker-surface]')
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
        // Native dialog backdrop clicks target the dialog itself, not its contents.
        if (event.target === this.dialog) {
            const clickedBackdrop = this.pointerDownOnBackdrop
                && this.isOutsideDialog(event.clientX, event.clientY)
            this.pointerDownOnBackdrop = false
            if (clickedBackdrop && !this.uploading) this.close(true)
            return
        }
        this.pointerDownOnBackdrop = false

        if (this.handleFolderMenuClick(event)) return

        const cancel = event.target.closest('[data-picker-cancel]')
        if (cancel) {
            if (!this.uploading) this.close(true)
            return
        }

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

        const openMenu = this.dialog.querySelector('[data-picker-new-folder].is-open')
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
        if (event.target.matches('[data-picker-upload]')) {
            this.uploadFiles(event.target.files)
        }
    }

    itemFromButton(button) {
        return {
            id: Number(button.dataset.id),
            reference: button.dataset.reference,
            name: button.dataset.name,
            thumbnail_url: button.dataset.thumbnailUrl,
            size: button.dataset.size ? Number(button.dataset.size) : null,
            uploaded_at: button.dataset.uploadedAt,
        }
    }

    toggleItem(item) {
        const id = String(item.id)
        if (this.selected.has(id)) {
            this.selected.delete(id)
        } else {
            if (!this.multiple) this.selected.clear()
            this.selected.set(id, item)
        }
        this.syncSurface()
        dispatchPickerEvent(this.origin, 'sb-media-picker:selection-change', {
            items: Array.from(this.selected.values()),
            multiple: this.multiple,
        })
    }

    updateDoneButton() {
        const button = this.dialog.querySelector('[data-picker-done]')
        if (!button) return
        button.disabled = this.selected.size === 0
        button.textContent = this.multiple && this.selected.size
            ? `${button.dataset.label} (${this.selected.size})`
            : button.dataset.label
    }

    uploadUrl() {
        return this.dialog.querySelector('[data-picker-upload-url]')?.dataset.pickerUploadUrl
    }

    hasDraggedFiles(event) {
        return Array.from(event.dataTransfer?.types || []).includes('Files')
    }

    setDropzoneActive(active) {
        this.dialog.querySelector('[data-picker-surface]')?.classList.toggle('is-dragging', active)
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
        const loading = this.dialog.querySelector('[data-picker-loading]')
        if (!loading) return
        loading.querySelector('[data-picker-loading-text]').textContent =
            `${loading.dataset.uploadingLabel} ${current}/${total} (${percent}%)`
        loading.classList.add('is-uploading')
    }

    clearUploadProgress() {
        const loading = this.dialog.querySelector('[data-picker-loading]')
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
        const pickerType = this.dialog.querySelector('[data-picker-surface]')?.dataset.pickerType
        const files = Array.from(fileList || []).filter(
            (file) => pickerType !== PICKER_TYPE_IMAGE || file.type.startsWith('image/'),
        )
        const uploadUrl = this.uploadUrl()
        if (!files.length || !uploadUrl || this.uploading) return

        this.uploading = true
        this.dialog.querySelector('[data-picker-status]').textContent = ''
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
        } catch (error) {
            this.dialog.querySelector('[data-picker-status]').textContent = error.message || String(error)
        } finally {
            this.uploading = false
            this.clearUploadProgress()
            const input = this.dialog.querySelector('[data-picker-upload]')
            if (input) input.value = ''
        }
    }

    refreshSurface() {
        const surface = this.dialog.querySelector('[data-picker-surface]')
        const filters = surface.querySelector('[data-picker-filters]')
        const url = new URL(surface.dataset.endpoint, window.location.href)
        new FormData(filters).forEach((value, key) => url.searchParams.set(key, value))
        return window.htmx.ajax('GET', url.toString(), {target: surface, swap: 'outerHTML'})
    }

    finish() {
        const items = Array.from(this.selected.values())
        const detail = {items, item: items[0] || null, multiple: this.multiple}
        dispatchPickerEvent(this.origin, 'sb-media-picker:select', detail)
        if (typeof this.options.onSelect === 'function') this.options.onSelect(detail)
        this.close(false)
    }

    close(cancelled) {
        if (this.uploading || !this.dialog.isConnected) return
        document.removeEventListener('htmx:afterSwap', this.handleAfterSwap)
        document.removeEventListener('keydown', this.handleKeyDown, true)
        document.body.classList.remove('sb-media-picker-open')
        this.dialog.close()
        this.dialog.remove()
        if (cancelled) dispatchPickerEvent(this.origin, 'sb-media-picker:cancel', {})
        this.restoreFocus?.focus()
    }
}

let activePicker = null

const open = (options) => {
    if (!options?.endpoint) throw new Error('SBMediaPicker requires an endpoint')
    if (!window.htmx) throw new Error('SBMediaPicker requires HTMX')
    if (activePicker?.uploading) return activePicker
    activePicker?.close(true)
    activePicker = new MediaPicker(options)
    return activePicker
}

window.SBMediaPicker = {open}

const widgetSelectedItem = (widget) => {
    const input = widget.querySelector('.vForeignKeyRawIdAdminField')
    const id = input?.value
    if (!id) return null

    try {
        const stored = JSON.parse(widget.querySelector('script[type="application/json"]')?.textContent || 'null')
        if (String(stored?.id) === String(id)) return stored
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
    return {
        id: Number(id),
        reference: `filer://${widget.dataset.pickerType}/${id}`,
        name,
        thumbnail_url: image?.src || '',
        size: null,
        uploaded_at: '',
    }
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

document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-sb-media-picker-trigger]')
    if (trigger) {
        const widget = trigger.closest('[data-sb-media-picker-widget]')
        const item = widgetSelectedItem(widget)
        const selected = item ? [item] : []
        open({endpoint: widget.dataset.endpoint, selected, origin: widget})
    }

    const clear = event.target.closest('[data-picker-clear]')
    if (clear) updateWidget(clear.closest('[data-sb-media-picker-widget]'), null)
})

document.addEventListener('sb-media-picker:select', (event) => {
    if (event.target.matches?.('[data-sb-media-picker-widget]')) updateWidget(event.target, event.detail.item)
})
