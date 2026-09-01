import { Editor, Node, ResizableNodeView, mergeAttributes } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import { Color } from '@tiptap/extension-color'
import { TextStyle } from '@tiptap/extension-text-style'
import TextAlign from '@tiptap/extension-text-align'
import Link from '@tiptap/extension-link'
import {
    Table,
    TableCell,
    TableHeader,
    TableRow,
} from '@tiptap/extension-table'

const FILER_IMAGE_ID_PATTERN = /^[1-9]\d*$/
const IMAGE_WIDTH_PATTERN = /^(\d+(?:\.\d+)?)(%|px)$/
const MAX_IMAGE_DIMENSION = 5760
const DEFAULT_IMAGE_WIDTH = '100%'
const MEDIA_PICKER_SELECTED_EVENT = 'sbadmin:media-picker:selected'
const SET_VALUE_EVENT = 'sbadmin:richtext:set-value'
const WIDGET_SELECTOR = '[data-sbadmin-richtext]'
const controllers = new WeakMap()
const lazyEditorObserver = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) controllers.get(entry.target)?.initializeEditor?.()
        })
    }, {rootMargin: '200px'})
    : null

function sanitizeImageWidth(value) {
    const match = String(value || '').trim().match(IMAGE_WIDTH_PATTERN)
    if (!match) return null
    const width = Number(match[1])
    const maximum = match[2] === '%' ? 100 : MAX_IMAGE_DIMENSION
    if (!Number.isFinite(width) || width <= 0 || width > maximum) return null
    return `${width}${match[2]}`
}

function imageWidthFromElement(element) {
    let styleWidth = null
    String(element.getAttribute('style') || '').split(';').forEach((declaration) => {
        const separator = declaration.indexOf(':')
        if (separator === -1) return
        const name = declaration.slice(0, separator).trim().toLowerCase()
        const styleValue = declaration.slice(separator + 1).trim()
        if (name !== 'width') return
        styleWidth = sanitizeImageWidth(styleValue)
    })
    if (styleWidth) return styleWidth

    const widthAttribute = String(element.getAttribute('width') || '').trim()
    const widthWithUnit = /^\d+(?:\.\d+)?$/.test(widthAttribute)
        ? `${widthAttribute}px`
        : widthAttribute
    return sanitizeImageWidth(widthWithUnit) || DEFAULT_IMAGE_WIDTH
}

function imageWidthStyle(value) {
    return `width: ${sanitizeImageWidth(value) || DEFAULT_IMAGE_WIDTH}`
}

function editorContentWidth(view) {
    const element = view.dom
    const style = window.getComputedStyle(element)
    const padding = Number.parseFloat(style.paddingLeft || '0')
        + Number.parseFloat(style.paddingRight || '0')
    return Math.max(1, element.clientWidth - padding)
}

function percentageImageWidth(width, view) {
    const percentage = Math.min(100, Math.max(1, width / editorContentWidth(view) * 100))
    return `${Math.round(percentage * 10) / 10}%`
}

function staticImageNodeView({node, image, updateImage}) {
    const render = (currentNode) => {
        updateImage(image, currentNode)
        image.style.width = sanitizeImageWidth(currentNode.attrs.resizeWidth)
            || DEFAULT_IMAGE_WIDTH
        image.style.height = 'auto'
    }
    render(node)
    image.draggable = false
    return {
        dom: image,
        update(updatedNode) {
            if (updatedNode.type !== node.type) return false
            render(updatedNode)
            return true
        },
    }
}

function resizableImageNodeView({node, editor, view, getPos, image, updateImage}) {
    if (!editor.isEditable) return staticImageNodeView({node, image, updateImage})

    updateImage(image, node)
    let nodeView = null

    const applyWidth = (width) => {
        nodeView.container.style.width = sanitizeImageWidth(width) || DEFAULT_IMAGE_WIDTH
        nodeView.wrapper.style.width = '100%'
        image.style.width = '100%'
        image.style.height = 'auto'
    }

    nodeView = new ResizableNodeView({
        editor,
        element: image,
        node,
        getPos,
        onResize: (width) => applyWidth(`${Math.min(width, editorContentWidth(view))}px`),
        onCommit: (width) => {
            let position
            try {
                position = getPos()
            } catch {
                return
            }
            if (!Number.isInteger(position)) return
            const currentNode = view.state.doc.nodeAt(position)
            if (!currentNode || currentNode.type !== node.type) return
            view.dispatch(view.state.tr.setNodeMarkup(
                position,
                undefined,
                {
                    ...currentNode.attrs,
                    resizeWidth: percentageImageWidth(width, view),
                },
                currentNode.marks,
            ))
        },
        onUpdate: (updatedNode) => {
            updateImage(image, updatedNode)
            applyWidth(updatedNode.attrs.resizeWidth)
            return true
        },
        options: {
            max: {width: editorContentWidth(view)},
            preserveAspectRatio: true,
            directions: ['top-left', 'top-right', 'bottom-left', 'bottom-right'],
            className: {
                container: 'sbadmin-richtext__resize-container',
                wrapper: 'sbadmin-richtext__resize-wrapper',
                handle: 'sbadmin-richtext__resize-handle',
                resizing: 'is-resizing',
            },
        },
    })
    applyWidth(node.attrs.resizeWidth)

    const refreshMaximumWidth = () => {
        nodeView.maxSize = {width: editorContentWidth(view)}
    }
    nodeView.container.addEventListener('mousedown', refreshMaximumWidth, true)
    nodeView.container.addEventListener('touchstart', refreshMaximumWidth, true)
    return nodeView
}

function filerImage(items, imageClass) {
    return Node.create({
        name: 'studioFilerImage',
        group: 'inline',
        inline: true,
        atom: true,
        draggable: true,

        addAttributes() {
            return {
                filerImageId: {
                    default: null,
                    parseHTML: (element) => element.getAttribute('data-filer-image-id'),
                },
                src: {
                    default: null,
                    parseHTML: (element) => element.getAttribute('src'),
                },
                alt: {
                    default: null,
                    parseHTML: (element) => element.getAttribute('alt'),
                },
                resizeWidth: {
                    default: DEFAULT_IMAGE_WIDTH,
                    parseHTML: imageWidthFromElement,
                },
            }
        },

        parseHTML() {
            return [{
                tag: 'img[data-filer-image-id]',
                getAttrs: (element) => (
                    FILER_IMAGE_ID_PATTERN.test(
                        element.getAttribute('data-filer-image-id') || '',
                    ) ? null : false
                ),
            }]
        },

        renderHTML({HTMLAttributes}) {
            const {
                filerImageId,
                resizeWidth,
                src,
                alt,
                ...attributes
            } = HTMLAttributes
            const item = items[filerImageId] || {}
            const resolvedSrc = item.original_url || src || item.thumbnail_url || null
            return ['img', mergeAttributes(attributes, {
                'data-filer-image-id': filerImageId,
                ...(resolvedSrc ? {src: resolvedSrc} : {}),
                alt: item.label || alt || '',
                style: imageWidthStyle(resizeWidth),
            })]
        },

        addNodeView() {
            return ({node, editor, view, getPos}) => {
                const image = document.createElement('img')
                image.className = imageClass
                return resizableImageNodeView({
                    node,
                    editor,
                    view,
                    getPos,
                    image,
                    updateImage: (element, currentNode) => {
                        const item = items[currentNode.attrs.filerImageId] || {}
                        element.src = item.original_url
                            || currentNode.attrs.src
                            || item.thumbnail_url
                            || ''
                        element.alt = item.label || currentNode.attrs.alt || ''
                        element.dataset.filerImageId = currentNode.attrs.filerImageId
                    },
                })
            }
        },
    })
}

const OrdinaryImage = Node.create({
    name: 'ordinaryImage',
    group: 'inline',
    inline: true,
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            src: {default: null},
            alt: {default: null},
            title: {default: null},
            loading: {default: null},
            resizeWidth: {
                default: DEFAULT_IMAGE_WIDTH,
                parseHTML: imageWidthFromElement,
            },
        }
    },

    parseHTML() {
        return [{
            tag: 'img',
            getAttrs: (element) => (
                FILER_IMAGE_ID_PATTERN.test(
                    element.getAttribute('data-filer-image-id') || '',
                ) ? false : null
            ),
        }]
    },

    renderHTML({HTMLAttributes}) {
        const {resizeWidth, ...attributes} = HTMLAttributes
        return ['img', mergeAttributes(attributes, {style: imageWidthStyle(resizeWidth)})]
    },

    addNodeView() {
        return ({node, editor, view, getPos}) => {
            const image = document.createElement('img')
            return resizableImageNodeView({
                node,
                editor,
                view,
                getPos,
                image,
                updateImage: (element, currentNode) => {
                    const attributes = ['src', 'alt', 'title', 'loading']
                    attributes.forEach((attribute) => {
                        const value = currentNode.attrs[attribute]
                        if (value === null || value === '') element.removeAttribute(attribute)
                        else element.setAttribute(attribute, value)
                    })
                },
            })
        }
    },
})

const RichTextTable = Table.extend({
    renderHTML() {
        return ['table', {}, ['tbody', 0]]
    },
})

function editorExtensions(items, imageClass) {
    return [
        StarterKit.configure({
            blockquote: false,
            code: false,
            codeBlock: false,
            heading: {levels: [2, 3, 4, 5, 6]},
            horizontalRule: false,
            link: false,
            strike: false,
            underline: false,
        }),
        Underline,
        TextStyle,
        Color,
        TextAlign.configure({types: ['heading', 'paragraph']}),
        Link.configure({
            openOnClick: false,
            autolink: false,
            defaultProtocol: 'https',
            protocols: ['http', 'https', 'mailto', 'tel'],
            HTMLAttributes: {target: null, rel: null, class: null},
        }),
        RichTextTable.configure({resizable: false}),
        TableRow,
        TableHeader,
        TableCell,
        filerImage(items, imageClass),
        OrdinaryImage,
    ]
}

function readItems(root) {
    const itemsId = root.dataset.richtextItemsId
    const element = itemsId ? document.getElementById(itemsId) : null
    return element ? JSON.parse(element.textContent) : {}
}

function editorValue(editor) {
    return editor.isEmpty ? '' : editor.getHTML()
}

function createEditor({
    element,
    content = '',
    items = {},
    imageClass = 'sbadmin-richtext__image',
    editable = true,
    attributes = {},
    onUpdate,
    onBlur,
    onFocus,
    onTransaction,
}) {
    return new Editor({
        element,
        extensions: editorExtensions(items, imageClass),
        content,
        editable,
        editorProps: {attributes},
        onUpdate: ({editor}) => onUpdate?.(editorValue(editor), editor),
        onBlur: ({editor}) => onBlur?.(editorValue(editor), editor),
        onFocus: ({editor}) => onFocus?.(editor),
        onTransaction: ({editor}) => onTransaction?.(editor),
    })
}

class RichTextWidgetController {
    constructor(root, options = {}) {
        this.root = root
        this.textarea = root.querySelector('textarea')
        this.editorElement = root.querySelector('[data-richtext-editor]')
        this.readonly = root.dataset.richtextReadonly === 'true'
        this.items = options.items || readItems(root)
        this.onUpdate = options.onUpdate
        this.onImage = options.onImage
        this.sourceMode = false
        this.editorHasFocused = false
        this.editor = null
        this.destroyed = false
        this.initializeEditor = this.initializeEditor.bind(this)
        this.handleClick = this.handleClick.bind(this)
        this.handleBlockChange = this.handleBlockChange.bind(this)
        this.handleColorChange = this.handleColorChange.bind(this)
        this.handleMediaSelection = this.handleMediaSelection.bind(this)
        this.handleSetValue = this.handleSetValue.bind(this)
        this.handleDocumentClick = this.handleDocumentClick.bind(this)
        this.handleKeydown = this.handleKeydown.bind(this)
        root.addEventListener('pointerenter', this.initializeEditor)
        root.addEventListener('focusin', this.initializeEditor)
        root.addEventListener('click', this.handleClick)
        root.querySelector('[data-richtext-block]')?.addEventListener('change', this.handleBlockChange)
        root.querySelector('[data-richtext-color]')?.addEventListener('input', this.handleColorChange)
        root.addEventListener(MEDIA_PICKER_SELECTED_EVENT, this.handleMediaSelection)
        root.addEventListener(SET_VALUE_EVENT, this.handleSetValue)
        root.addEventListener('keydown', this.handleKeydown)
        document.addEventListener('click', this.handleDocumentClick)
        if (this.readonly) this.initializeEditor()
        else if (lazyEditorObserver) lazyEditorObserver.observe(root)
        else this.initializeEditor()
    }

    initializeEditor() {
        if (this.editor !== null || this.destroyed) return this.editor
        lazyEditorObserver?.unobserve(this.root)
        this.root.removeEventListener('pointerenter', this.initializeEditor)
        this.root.removeEventListener('focusin', this.initializeEditor)
        this.editor = createEditor({
            element: this.editorElement,
            content: this.textarea.value || '',
            items: this.items,
            editable: !this.readonly,
            attributes: {
                class: 'sbadmin-richtext__content',
                'aria-labelledby': this.textarea.id,
            },
            onUpdate: (value) => {
                this.syncTextarea(value, 'input')
                this.onUpdate?.(value)
            },
            onBlur: () => this.textarea.dispatchEvent(new Event('change', {bubbles: true})),
            onFocus: (editor) => {
                this.editorHasFocused = true
                this.syncToolbar(editor)
            },
            onTransaction: (editor) => this.syncToolbar(editor),
        })
        this.syncToolbar(this.editor)
        return this.editor
    }

    syncTextarea(value, eventName = null) {
        this.textarea.value = value
        if (eventName) this.textarea.dispatchEvent(new Event(eventName, {bubbles: true}))
    }

    syncItemsElement() {
        const itemsId = this.root.dataset.richtextItemsId
        const itemsElement = itemsId ? document.getElementById(itemsId) : null
        if (itemsElement) itemsElement.textContent = JSON.stringify(this.items)
    }

    applySourceValue() {
        this.initializeEditor()
        this.editor.commands.setContent(this.textarea.value, {emitUpdate: false})
    }

    chain() {
        return this.initializeEditor().chain().focus()
    }

    syncToolbar(editor = this.editor) {
        if (!editor || this.readonly) return

        const sourceModeControls = this.root.querySelectorAll([
            '[data-richtext-action]',
            '[data-richtext-block]',
            '[data-richtext-color]',
            '[data-richtext-table-menu-trigger]',
        ].join(','))
        sourceModeControls.forEach((control) => {
            const isSourceToggle = control.dataset.richtextAction === 'source'
            if (this.sourceMode && !isSourceToggle && !control.disabled) {
                control.disabled = true
                control.dataset.richtextDisabledBySource = ''
            } else if (!this.sourceMode && control.hasAttribute('data-richtext-disabled-by-source')) {
                control.disabled = false
                delete control.dataset.richtextDisabledBySource
            }
        })

        const blockSelect = this.root.querySelector('[data-richtext-block]')
        const activeHeading = [2, 3, 4, 5, 6].find(
            (level) => editor.isActive('heading', {level}),
        )
        if (blockSelect) blockSelect.value = String(activeHeading || 0)

        const tableMenu = this.root.querySelector('[data-richtext-table-menu]')
        const tableMenuTrigger = this.root.querySelector('[data-richtext-table-menu-trigger]')
        const tableIsActive = this.editorHasFocused
            && !this.sourceMode
            && editor.isActive('table')
        if (tableMenu) {
            tableMenu.hidden = !tableIsActive
            if (!tableIsActive) this.closeTableMenu()
        }
        tableMenuTrigger?.classList.toggle('is-active', tableIsActive)
        tableMenuTrigger?.setAttribute('aria-pressed', String(tableIsActive))

        const alignCenter = editor.isActive({textAlign: 'center'})
        const alignRight = editor.isActive({textAlign: 'right'})
        const alignJustify = editor.isActive({textAlign: 'justify'})
        const activeActions = {
            bold: editor.isActive('bold'),
            italic: editor.isActive('italic'),
            underline: editor.isActive('underline'),
            link: editor.isActive('link'),
            'align-left': editor.isActive({textAlign: 'left'})
                || !(alignCenter || alignRight || alignJustify),
            'align-center': alignCenter,
            'align-right': alignRight,
            'align-justify': alignJustify,
            'bullet-list': editor.isActive('bulletList'),
            'ordered-list': editor.isActive('orderedList'),
        }
        Object.entries(activeActions).forEach(([action, active]) => {
            const button = this.root.querySelector(`[data-richtext-action="${action}"]`)
            button?.classList.toggle('is-active', active)
            button?.setAttribute('aria-pressed', String(active))
        })

        const color = editor.getAttributes('textStyle').color
        const colorInput = this.root.querySelector('[data-richtext-color]')
        if (colorInput && /^#[0-9a-f]{6}$/i.test(color || '')) colorInput.value = color
    }

    toggleTableMenu() {
        const options = this.root.querySelector('[data-richtext-table-menu-options]')
        const trigger = this.root.querySelector('[data-richtext-table-menu-trigger]')
        if (!options || !trigger) return
        options.hidden = !options.hidden
        trigger.setAttribute('aria-expanded', String(!options.hidden))
        if (!options.hidden) {
            options.style.left = '0'
            options.style.right = 'auto'
            const toolbar = trigger.closest('.sbadmin-richtext__toolbar')
            const menuOverflows = toolbar
                && options.getBoundingClientRect().right > toolbar.getBoundingClientRect().right
            if (menuOverflows) {
                options.style.left = 'auto'
                options.style.right = '0'
            }
        }
    }

    closeTableMenu() {
        const options = this.root.querySelector('[data-richtext-table-menu-options]')
        const trigger = this.root.querySelector('[data-richtext-table-menu-trigger]')
        if (options) options.hidden = true
        trigger?.setAttribute('aria-expanded', 'false')
    }

    handleDocumentClick(event) {
        if (!this.root.contains(event.target)) this.closeTableMenu()
    }

    handleKeydown(event) {
        if (event.key !== 'Escape') return
        const options = this.root.querySelector('[data-richtext-table-menu-options]')
        if (!options || options.hidden) return
        this.closeTableMenu()
        this.root.querySelector('[data-richtext-table-menu-trigger]')?.focus()
    }

    handleBlockChange(event) {
        if (this.sourceMode) return
        const level = Number(event.target.value)
        if (level === 0) this.chain().setParagraph().run()
        else this.chain().toggleHeading({level}).run()
    }

    handleColorChange(event) {
        if (this.sourceMode) return
        this.chain().setColor(event.target.value).run()
    }

    async openImagePicker() {
        if (!this.onImage) return
        const item = await this.onImage()
        if (this.destroyed || !item) return
        this.handleMediaSelection({detail: {item}})
    }

    handleMediaSelection(event) {
        const item = event.detail?.item
        const imageId = String(item?.id || '')
        if (!FILER_IMAGE_ID_PATTERN.test(imageId)) return
        this.items[imageId] = {
            label: item.name || '',
            thumbnail_url: item.thumbnail_url || '',
            original_url: item.original_url || '',
        }
        this.syncItemsElement()
        if (this.sourceMode) this.applySourceValue()
        const chain = this.sourceMode ? this.editor.chain() : this.chain()
        chain.insertContent({
            type: 'studioFilerImage',
            attrs: {
                filerImageId: imageId,
                src: item.original_url || item.thumbnail_url || null,
                alt: item.name || '',
                resizeWidth: DEFAULT_IMAGE_WIDTH,
            },
        }).run()
    }

    handleSetValue(event) {
        Object.entries(event.detail?.items || {}).forEach(([imageId, item]) => {
            if (FILER_IMAGE_ID_PATTERN.test(imageId)) this.items[imageId] = item
        })
        this.syncItemsElement()
        this.setValue(String(event.detail?.value || ''))
    }

    setValue(value) {
        this.initializeEditor()
        this.editor.commands.setContent(value, {emitUpdate: false})
        this.syncTextarea(editorValue(this.editor), 'input')
        this.textarea.dispatchEvent(new Event('change', {bubbles: true}))
    }

    openLinkDialog() {
        this.initializeEditor()
        const dialog = this.root.querySelector('[data-richtext-link-dialog]')
        const input = this.root.querySelector('[data-richtext-link-url]')
        input.value = this.editor.getAttributes('link').href || ''
        dialog.classList.remove('hidden')
        input.focus()
    }

    closeLinkDialog() {
        this.root.querySelector('[data-richtext-link-dialog]')?.classList.add('hidden')
    }

    applyLink() {
        const href = this.root.querySelector('[data-richtext-link-url]').value.trim()
        if (href) this.chain().extendMarkRange('link').setLink({href}).run()
        else this.chain().unsetLink().run()
        this.closeLinkDialog()
    }

    toggleSource(button) {
        this.initializeEditor()
        if (this.sourceMode) {
            this.applySourceValue()
            this.syncTextarea(editorValue(this.editor), 'input')
        } else {
            this.syncTextarea(editorValue(this.editor))
        }
        this.sourceMode = !this.sourceMode
        button.classList.toggle('is-active', this.sourceMode)
        this.editorElement.classList.toggle('hidden', this.sourceMode)
        this.textarea.classList.toggle('hidden', !this.sourceMode)
        if (this.sourceMode) this.textarea.focus()
        this.syncToolbar(this.editor)
    }

    handleClick(event) {
        if (event.target.closest('[data-richtext-editor]')) {
            this.editorHasFocused = true
            this.syncToolbar(this.editor)
        }
        const tableMenuTrigger = event.target.closest('[data-richtext-table-menu-trigger]')
        if (tableMenuTrigger && this.root.contains(tableMenuTrigger)) {
            if (this.sourceMode) return
            this.toggleTableMenu()
            return
        }
        const button = event.target.closest('[data-richtext-action]')
        if (!button || !this.root.contains(button)) {
            if (!event.target.closest('[data-richtext-table-menu]')) this.closeTableMenu()
            return
        }
        if (this.sourceMode && button.dataset.richtextAction !== 'source') return
        const actions = {
            bold: () => this.chain().toggleBold().run(),
            italic: () => this.chain().toggleItalic().run(),
            underline: () => this.chain().toggleUnderline().run(),
            'align-left': () => this.chain().setTextAlign('left').run(),
            'align-center': () => this.chain().setTextAlign('center').run(),
            'align-right': () => this.chain().setTextAlign('right').run(),
            'align-justify': () => this.chain().setTextAlign('justify').run(),
            link: () => this.openLinkDialog(),
            image: () => this.openImagePicker(),
            table: () => this.chain().insertTable({rows: 3, cols: 3, withHeaderRow: true}).run(),
            'add-table-row': () => this.chain().addRowAfter().run(),
            'add-table-column': () => this.chain().addColumnAfter().run(),
            'delete-table-row': () => this.chain().deleteRow().run(),
            'delete-table-column': () => this.chain().deleteColumn().run(),
            'delete-table': () => this.chain().deleteTable().run(),
            'bullet-list': () => this.chain().toggleBulletList().run(),
            'ordered-list': () => this.chain().toggleOrderedList().run(),
            indent: () => this.chain().sinkListItem('listItem').run(),
            outdent: () => this.chain().liftListItem('listItem').run(),
            clear: () => this.chain().unsetAllMarks().clearNodes().run(),
            source: () => this.toggleSource(button),
            'apply-link': () => this.applyLink(),
            'remove-link': () => {
                this.chain().extendMarkRange('link').unsetLink().run()
                this.closeLinkDialog()
            },
            'cancel-link': () => this.closeLinkDialog(),
        }
        actions[button.dataset.richtextAction]?.()
        this.closeTableMenu()
    }

    destroy() {
        this.destroyed = true
        lazyEditorObserver?.unobserve(this.root)
        this.root.removeEventListener('pointerenter', this.initializeEditor)
        this.root.removeEventListener('focusin', this.initializeEditor)
        this.root.removeEventListener('click', this.handleClick)
        this.root.querySelector('[data-richtext-block]')?.removeEventListener('change', this.handleBlockChange)
        this.root.querySelector('[data-richtext-color]')?.removeEventListener('input', this.handleColorChange)
        this.root.removeEventListener(MEDIA_PICKER_SELECTED_EVENT, this.handleMediaSelection)
        this.root.removeEventListener(SET_VALUE_EVENT, this.handleSetValue)
        this.root.removeEventListener('keydown', this.handleKeydown)
        document.removeEventListener('click', this.handleDocumentClick)
        this.editor?.destroy()
        this.editor = null
        controllers.delete(this.root)
    }
}

function initializeWidget(root, options = {}) {
    if (!controllers.has(root)) {
        controllers.set(root, new RichTextWidgetController(root, options))
    }
    return controllers.get(root)
}

function destroyWidget(root) {
    controllers.get(root)?.destroy()
}

function initializeWidgets(target = document) {
    const roots = []
    if (target.matches?.(WIDGET_SELECTOR)) roots.push(target)
    roots.push(...target.querySelectorAll?.(WIDGET_SELECTOR) || [])
    roots.forEach((root) => initializeWidget(root))
}

window.SBAdminRichText = Object.freeze({
    createEditor,
    destroyWidget,
    editorValue,
    initializeWidget,
})

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initializeWidgets(), {once: true})
} else {
    initializeWidgets()
}

document.addEventListener('formset:added', (event) => initializeWidgets(event.target))
document.addEventListener('htmx:beforeSwap', (event) => {
    const target = event.detail?.target
    if (!target) return
    const roots = []
    if (target.matches?.(WIDGET_SELECTOR)) roots.push(target)
    roots.push(...target.querySelectorAll?.(WIDGET_SELECTOR) || [])
    roots.forEach((root) => controllers.get(root)?.destroy())
})
document.addEventListener('htmx:afterSwap', (event) => initializeWidgets(event.detail?.elt || document))
