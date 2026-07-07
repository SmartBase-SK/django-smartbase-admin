import Dropdown from 'bootstrap/js/dist/dropdown'
import Collapse from 'bootstrap/js/dist/collapse'
import Tab from 'bootstrap/js/dist/tab'
import Modal from 'bootstrap/js/dist/modal'
import Tooltip from 'bootstrap/js/dist/tooltip'
import Popover from 'bootstrap/js/dist/popover'
import debounce from 'lodash/debounce'

// remove Modal focus trap to fix interaction with fields in modals inside another modal
Modal.prototype._initializeFocusTrap = function () {
    return {
        activate: function () {
        }, deactivate: function () {
        }
    }
}

window.bootstrap5 = {
    Modal: Modal,
    Tooltip: Tooltip,
    Popover: Popover,
    Collapse: Collapse,
    Tab: Tab,
    Dropdown: Dropdown
}

import Sidebar from "./sidebar"
import Datepicker from "./datepicker"
import Range from "./range"
import Sorting from "./sorting"
import Autocomplete from "./autocomplete"
import StaticAutocomplete from "./static_autocomplete"
import ChoicesJS from "./choices"
import TextTags from "./text_tags"
import { ensureFilterForms, setCookie, setDropdownLabel, shouldProcessAfterSwap } from "./utils"
import Multiselect from "./multiselect"
import Radio from "./radio"
import "./inline_paginator"

const CKEDITOR_READY_MAX_FRAMES = 120
const PAGE_SCROLL_MARGIN_PX = 24
const MODAL_SCROLL_MARGIN_PX = 24
const SBADMIN_MAIN_LOADED_EVENT = 'SBAdminMainLoaded'
const COPY_BUTTON_SELECTOR = '[data-sbadmin-copy-button]'
const COPIED_TIMEOUT_MS = 1500
const NOTIFICATION_SLOT_ID = 'notification-messages'
const NOTIFICATION_AUTO_REMOVE_TIMEOUT = '5s'
const NOTIFICATION_TYPES = new Set(['success', 'warning', 'negative', 'notice'])

class Main {
    constructor() {
        document.body.classList.add('js-ready')
        ensureFilterForms()
        this.handleColorSchemeChange()
        this.initTooltips()
        this.initDropdowns()
        document.addEventListener('formset:added', (e) => {
            ensureFilterForms(e.target)
            this.initTooltips(e.target)
            this.initDropdowns(e.target)
            this.initFileInputs(e.target)
            this.switchCKEditorTheme(e.target)
            if (e.target !== e.target.parentNode.firstChild) {
                e.target.parentNode.insertBefore(e.target, e.target.parentNode.firstChild)
            }
            window.htmx.process(e.target)
        })
        document.addEventListener('openUrl', (e) => {
            window.open(e.detail.url, e.detail?.target || '_blank', 'noopener')
        })

        if (window.htmx) {
            const processAfterSwap = (target) => {
                ensureFilterForms(target)
                this.initFileInputs(target)
                this.initDropdowns(target)
                this.initInputs(target)
                this.autocomplete.handleDynamiclyAddedAutocomplete(target)
                this.staticAutocomplete.handleDynamicallyAdded(target)
                this.textTags.handleDynamicallyAddedTextTags(target)
                this.initInlines(target)
                this.initTooltips(target)
                this.syncEmptyFieldsets(target)
                this.scheduleScrollToFirstErrorField(target)
            }
            window.htmx.on("htmx:afterSwap", (event) => {
                if (!shouldProcessAfterSwap(event)) {
                    return
                }
                processAfterSwap(event.detail.elt)
            })

            window.htmx.on("htmx:oobAfterSwap", (event) => {
                // fix duplicit oobAfterSwap events triggered for multiple oob swaps
                // https://github.com/bigskysoftware/htmx/issues/1803
                const target = event.detail.elt
                const swapTarget = event.detail.target
                if (!target || !swapTarget || (target !== swapTarget && target.id !== swapTarget.id)) {
                    return
                }
                processAfterSwap(target)
            })

            window.htmx.on("htmx:afterSettle", (event) => {
                this.switchCKEditorTheme(event.detail.elt)
                this.syncEmptyFieldsets(document)
            })
        }

        new Sidebar()
        this.initInputs()
        new Sorting()
        this.autocomplete = new Autocomplete()
        this.staticAutocomplete = new StaticAutocomplete()
        this.textTags = new TextTags()
        this.choicesJS = new ChoicesJS()
        document.addEventListener('click', (e) => {
            this.closeAlert(e)
            this.selectAll(e)
            this.saveState(e)
            this.fileDownload(e)
            this.copyToClipboard(e)
            this.passwordToggleFnc(e)
            this.collapseStackedInlineButtons(e)
        })
        this.initFileInputs()
        this.initAliasName()
        this.handleLocationHashFromTabs()
        this.initCollapseEventListeners()
        this.syncEmptyFieldsets(document)
        this.scheduleScrollToFirstErrorField(document)
    }

    isHiddenWithinFieldset(element, fieldset) {
        let current = element
        while (current && current !== fieldset) {
            if (current.hidden || current.classList?.contains('hidden')) {
                return true
            }
            current = current.parentElement
        }
        return false
    }

    fieldsetHasVisibleFieldRows(fieldset) {
        return Array.from(fieldset.querySelectorAll('.field')).some((fieldRow) => {
            return !this.isHiddenWithinFieldset(fieldRow, fieldset)
        })
    }

    fieldsetHasVisibleDynamicRegionContent(fieldset) {
        return Array.from(fieldset.querySelectorAll('[data-sbadmin-dynamic-region-content]')).some((region) => {
            if (this.isHiddenWithinFieldset(region, fieldset)) {
                return false
            }
            return region.dataset.sbadminDynamicRegionVisible === 'true' &&
                (region.dataset.sbadminDynamicRegionTemplate === 'true' ||
                    region.dataset.sbadminDynamicRegionDeferred === 'true')
        })
    }

    fieldsetHasErrors(fieldset) {
        return Boolean(fieldset.querySelector('.errorlist, .errors'))
    }

    syncEmptyFieldsets(target = document) {
        const selector = 'fieldset[data-sbadmin-hide-if-empty="true"]'
        const fieldsets = new Set()
        if (target.matches?.(selector)) {
            fieldsets.add(target)
        }
        const closestFieldset = target.closest?.(selector)
        if (closestFieldset) {
            fieldsets.add(closestFieldset)
        }
        target.querySelectorAll?.(selector).forEach((fieldset) => fieldsets.add(fieldset))

        fieldsets.forEach((fieldset) => {
            const isEmpty = !this.fieldsetHasErrors(fieldset) &&
                !this.fieldsetHasVisibleFieldRows(fieldset) &&
                !this.fieldsetHasVisibleDynamicRegionContent(fieldset)
            fieldset.classList.toggle('hidden', isEmpty)
        })
    }

    isDarkMode() {
        const colorScheme = document.documentElement.dataset.theme
        let isDark = colorScheme === 'dark'
        if (!colorScheme || colorScheme === 'auto') {
            isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        }
        return isDark
    }

    handleColorSchemeChange() {
        const picker = document.querySelector('.js-color-scheme-picker')
        if (picker) {
            picker.addEventListener('change', (e) => {
                if (e.target.value) {
                    document.documentElement.setAttribute('data-theme', e.target.value)
                    this.switchBodyColorSchemeClass(true)
                    this.switchCKEditorTheme()
                    return
                }
                document.documentElement.removeAttribute('data-theme')
            })
        }
        this.switchBodyColorSchemeClass()
        this.switchCKEditorTheme()
    }

    switchBodyColorSchemeClass(fireEvents = false) {
        if (this.isDarkMode()) {
            document.body.classList.add('dark')
            if (fireEvents) {
                document.body.dispatchEvent(new CustomEvent('color-scheme-change', { detail: 'dark' }))
            }
            return
        }
        document.body.classList.remove('dark')
        if (fireEvents) {
            document.body.dispatchEvent(new CustomEvent('color-scheme-change', { detail: 'light' }))
        }
    }

    initInlines(target) {
        target = target || document
        const inlineGroups = []
        if (target.matches && target.matches('.inline-group')) {
            inlineGroups.push(target)
        }
        inlineGroups.push(...target.querySelectorAll('.inline-group'))
        inlineGroups.forEach(group => {
            window.django.jQuery(group).djangoFormset()
        })
    }

    initInputs(target) {
        this.datepicker = new Datepicker(target)
        this.range = new Range(null, null, target)
        this.multiselect = new Multiselect(null, null, target)
        this.radio = new Radio(null, target)
    }

    initTooltips(target) {
        target = target || document
        const tooltipTriggerList = [].slice.call(target.querySelectorAll('[data-bs-toggle="tooltip"]'))
        tooltipTriggerList.forEach((tooltipTriggerEl) => {
            const tooltipEl = tooltipTriggerEl.closest('.js-tooltip')
            const tooltipContainer = tooltipTriggerEl.dataset.bsContainer || tooltipEl
            if (tooltipContainer) {
                new Tooltip(tooltipTriggerEl, { container: tooltipContainer })
            }
        })
        const firstInlineErrorTooltip = target.querySelector('.djn-inline-field-error-tooltip[data-bs-toggle="tooltip"]')
        if (firstInlineErrorTooltip) {
            Tooltip.getInstance(firstInlineErrorTooltip)?.show()
        }
    }

    handleLocationHashFromTabs() {
        const tabEls = document.querySelectorAll('button[data-bs-toggle="tab"]:not([data-bs-disable-history])')
        tabEls.forEach(tab => {
            tab.addEventListener('shown.bs.tab', function (event) {
                window.location.hash = event.target.id.split("tab_")[1]
            })
        })
    }

    hasValidationErrors(target) {
        return Boolean(target.querySelector('.errorlist'))
    }

    findFirstErrorAnchor(target) {
        const fieldError = target.querySelector('.field.errors')
        if (fieldError) {
            return fieldError
        }

        const inlineCellError = target.querySelector('.djn-inline-form.has-errors td[class*="field-"] .errorlist')
        if (inlineCellError) {
            return inlineCellError.closest('td[class*="field-"]') || inlineCellError
        }

        const inlineRowError = target.querySelector('.djn-inline-form.has-errors')
        if (inlineRowError) {
            return inlineRowError
        }

        const nonFieldError = target.querySelector('.nonfield, ul.errorlist')
        if (nonFieldError) {
            const wrapper = nonFieldError.closest('.field, td[class*="field-"], .djn-inline-form')
            return wrapper || nonFieldError
        }

        return null
    }

    getFirstFocusableField(anchor) {
        if (anchor.matches('input, select, textarea, button')) {
            return anchor
        }
        return anchor.querySelector('input:not([type="hidden"]), select, textarea, button')
    }

    getTargetCKEditorIds(target) {
        if (!target?.querySelectorAll) {
            return []
        }
        return Array.from(target.querySelectorAll('textarea[data-type="ckeditortype"]'))
            .map((textarea) => textarea.id)
            .filter(Boolean)
    }

    areTargetCKEditorsReady(editorIds) {
        if (!window.CKEDITOR || !editorIds.length) {
            return true
        }
        return editorIds.every((editorId) => window.CKEDITOR.instances[editorId]?.status === 'ready')
    }

    scheduleScrollToFirstErrorField(target) {
        if (!this.hasValidationErrors(target)) {
            return
        }
        const editorIds = this.getTargetCKEditorIds(target)
        if (!window.CKEDITOR || !editorIds.length) {
            this.scrollToFirstErrorField(target)
            return
        }
        let frameCount = 0
        const waitForEditors = () => {
            const editorsReady = this.areTargetCKEditorsReady(editorIds)
            const reachedMaxFrames = frameCount >= CKEDITOR_READY_MAX_FRAMES
            if (editorsReady || reachedMaxFrames) {
                this.scrollToFirstErrorField(target)
                return
            }
            frameCount += 1
            window.requestAnimationFrame(waitForEditors)
        }
        window.requestAnimationFrame(waitForEditors)
    }

    scrollElementIntoViewport(anchor) {
        const modalBody = anchor.closest('.modal-body')
        const detailActionBar = document.querySelector('.detail-view-action-bar')
        const actionBarHeight = detailActionBar ? detailActionBar.getBoundingClientRect().height : 0
        const modalScrollMargin = `${MODAL_SCROLL_MARGIN_PX}px`
        const pageScrollMarginTop = `${actionBarHeight + PAGE_SCROLL_MARGIN_PX}px`
        const scrollMargins = modalBody
            ? { scrollMarginTop: modalScrollMargin, scrollMarginBottom: modalScrollMargin }
            : { scrollMarginTop: pageScrollMarginTop }
        const previousScrollMargins = {
            scrollMarginTop: anchor.style.scrollMarginTop,
            scrollMarginBottom: anchor.style.scrollMarginBottom
        }

        try {
            Object.entries(scrollMargins).forEach(([propertyName, propertyValue]) => {
                anchor.style[propertyName] = propertyValue
            })
            anchor.scrollIntoView({ behavior: 'instant', block: 'start', inline: 'nearest' })
        } finally {
            anchor.style.scrollMarginTop = previousScrollMargins.scrollMarginTop
            anchor.style.scrollMarginBottom = previousScrollMargins.scrollMarginBottom
        }
    }

    expandCollapsedAncestors(element) {
        const collapsedAncestors = []
        let current = element?.parentElement
        while (current) {
            if (current.classList?.contains('collapse') && !current.classList.contains('show')) {
                collapsedAncestors.push(current)
            }
            current = current.parentElement
        }
        const ancestorsToExpand = collapsedAncestors.reverse()
        if (!ancestorsToExpand.length) {
            return Promise.resolve()
        }

        return ancestorsToExpand.reduce((promiseChain, collapseElement) => {
            return promiseChain.then(() => {
                return new Promise((resolve) => {
                    if (collapseElement.classList.contains('show')) {
                        resolve()
                        return
                    }
                    const collapseInstance = Collapse.getOrCreateInstance(collapseElement)
                    let timeoutId = null
                    const complete = () => {
                        collapseElement.removeEventListener('shown.bs.collapse', complete)
                        if (timeoutId) {
                            window.clearTimeout(timeoutId)
                        }
                        resolve()
                    }
                    collapseElement.addEventListener('shown.bs.collapse', complete, { once: true })
                    timeoutId = window.setTimeout(complete, 450)
                    collapseInstance.show()
                })
            })
        }, Promise.resolve())
    }

    scrollToFirstErrorField(target) {
        target = target || document
        if (!this.hasValidationErrors(target)) {
            return
        }
        const anchor = this.findFirstErrorAnchor(target)
        if (!anchor) {
            return
        }
        const firstField = this.getFirstFocusableField(anchor)
        const scrollTarget = firstField || anchor
        this.expandCollapsedAncestors(scrollTarget).then(() => {
            this.scrollElementIntoViewport(scrollTarget)
            if (firstField) {
                firstField.focus({ preventScroll: true })
            }
        })
    }

    passwordToggleFnc(event) {
        const passwordToggle = event.target.closest('.js-password-toggle-show, .js-password-toggle-hide')
        if (passwordToggle) {
            const parentWrapper = passwordToggle.closest('.relative')
            const input = parentWrapper.querySelector('input')
            const showIcon = parentWrapper.querySelector('.js-password-toggle-show')
            const hideIcon = parentWrapper.querySelector('.js-password-toggle-hide')

            if (input.type === 'text') {
                hideIcon.style.display = "none"
                showIcon.style.display = ""
                input.type = 'password'
            } else {
                showIcon.style.display = "none"
                hideIcon.style.display = ""
                input.type = 'text'
            }
        }
    }

    fileDownload(event) {
        const button = event.target.closest('.js-file-button')
        if (button) {
            event.preventDefault()
            event.stopPropagation()
            const download_window = window.open(button.getAttribute("href"))
            download_window.onbeforeunload = () => {
                var event = new CustomEvent("file-downloaded")
                document.querySelector('body').dispatchEvent(event)
            }
        }
    }

    initDropdowns(target) {
        target = target || document
        const dropdowns = [].slice.call(target.querySelectorAll(
            '[data-bs-toggle="dropdown"]:not([data-sbadmin-managed-dropdown])'
        ))
        dropdowns.map((dropdownToggleEl) => {
            let offset = dropdownToggleEl.dataset['bsOffset']
            if (offset) {
                offset = JSON.parse(dropdownToggleEl.dataset['bsOffset'])
            } else {
                offset = [0, 8]
            }
            const dropdown = new Dropdown(dropdownToggleEl, {
                autoClose: 'outside',
                offset: offset,
                popperConfig(defaultBsPopperConfig) {
                    const elementConf = {}
                    if (dropdownToggleEl.dataset['bsPopperPlacement']) {
                        elementConf['placement'] = dropdownToggleEl.dataset['bsPopperPlacement']
                    }
                    return { ...defaultBsPopperConfig, ...elementConf, strategy: 'fixed' }
                }
            })
            const dropdownWrapper = dropdownToggleEl.closest('.js-dropdown-wrapper')
            if (dropdownWrapper) {
                const dropdownLabelEl = dropdownWrapper.querySelector('.js-dropdown-label')
                dropdown._menu.addEventListener('change', (event) => {
                    setDropdownLabel(dropdown._menu, dropdownLabelEl)
                    if (event.target.closest("input[type='radio']")) {
                        dropdown.hide()
                    }
                })
            }
            return dropdown
        })
    }

    initAliasName() {
        if (!window.sb_admin_const) {
            return
        }
        const aliasGroup = document.getElementById(window.sb_admin_const.GLOBAL_FILTER_ALIAS_WIDGET_ID)
        if (!aliasGroup) {
            return
        }

        const changeAliasName = () => {
            const currentAlias = aliasGroup.querySelector('input.js-alias-domain-name-value:checked') ||
                aliasGroup.querySelector('input[name="alias"]:checked')
            if (!currentAlias) {
                return
            }
            document.querySelectorAll('.js-alias-domain-name').forEach(item => {
                item.classList.remove('hidden')
                item.innerHTML = currentAlias.nextElementSibling.innerText
            })
        }

        changeAliasName()
        aliasGroup.addEventListener('change', () => {
            changeAliasName()
        })
    }

    saveState(event) {
        const saveStateEl = event.target.closest('.js-save-state')
        if (saveStateEl) {
            const isBsToggle = saveStateEl.dataset['bsToggle']
            if (isBsToggle === 'collapse') {
                const expanded = saveStateEl.getAttribute('aria-expanded') === 'true'
                setCookie(saveStateEl.id, expanded, expanded ? 1 : 0)
            }
        }
    }

    closeAlert(event) {
        if (event.target.closest('.js-alert-close')) {
            event.target.closest('.alert').remove()
        }
    }

    selectAll(event) {
        const wrapper = event.target.closest('.js-select-all-wrapper')

        if (wrapper) {
            const selectAll = event.target.closest('.js-select-all')
            const clearAll = event.target.closest('.js-clear-all')
            if (selectAll) {
                const target = selectAll.dataset['selectTarget'] || '.js-select-all-item'
                wrapper.querySelectorAll(target).forEach(el => {
                    el.checked = true
                    el.dispatchEvent(new Event('change'))
                })
                wrapper.querySelector('.js-clear-all').disabled = false
                selectAll.disabled = true
                return
            }

            if (clearAll) {
                const target = clearAll.dataset['clearTarget'] || '.js-select-all-item'
                wrapper.querySelectorAll(target).forEach(el => {
                    el.checked = false
                    el.dispatchEvent(new Event('change'))
                })
                wrapper.querySelector('.js-select-all').disabled = false
                clearAll.disabled = true
                return
            }
            wrapper.querySelector('.js-select-all').disabled = false
            wrapper.querySelector('.js-clear-all').disabled = false
        }
    }

    initFileInputs(target) {
        target = target || document
        target.querySelectorAll('.js-input-file').forEach(fileInput => {
            const input = fileInput.querySelector('input[type="file"]')
            const delete_checkbox = fileInput.querySelector('input[type="checkbox"]')
            input?.addEventListener('change', e => {
                if (delete_checkbox) {
                    delete_checkbox.checked = false
                }
                if (e.target.files[0]) {
                    fileInput.classList.add('filled')
                    fileInput.querySelectorAll('.js-input-file-image').forEach(el => {
                        const nameSplit = e.target.files[0].name.split('.')
                        const extension = nameSplit[nameSplit.length - 1]
                        if (['jpg', 'jpeg', 'png', 'svg', 'webp'].includes(extension)) {
                            el.src = URL.createObjectURL(e.target.files[0])
                            el.classList.add('border')
                            return
                        }
                        el.classList.remove('border')
                        if (window.sb_admin_const.SUPPORTED_FILE_TYPE_ICONS.includes(extension)) {
                            el.src = `${window.sb_admin_const.STATIC_BASE_PATH}/images/file_types/file-${extension}.svg`
                            return
                        }
                        el.src = `${window.sb_admin_const.STATIC_BASE_PATH}/images/file_types/file-other.svg`
                    })
                    fileInput.querySelector('.js-input-file-filename').innerHTML = e.target.files[0].name
                } else {
                    fileInput.classList.remove('filled')
                    fileInput.querySelector('.js-input-file-filename').innerHTML = ""
                }
            })

            const deleteButton = fileInput.querySelector('.js-input-file-delete')
            deleteButton?.addEventListener('click', () => {
                if (input?.disabled || delete_checkbox?.disabled) {
                    return
                }
                input.value = ""
                input.dispatchEvent(new Event('change'))
                if (delete_checkbox) {
                    delete_checkbox.checked = true
                }
            })
        })
    }

    initCKEditor(target, config, force = false) {
        if (!window.CKEDITOR) {
            return
        }
        target = target || document
        target.querySelectorAll('textarea[data-type="ckeditortype"]').forEach((textarea) => {
            if (force || textarea.getAttribute("data-processed") == "0") {
                if (textarea.id.indexOf("__prefix__") == -1) {
                    this.reinitCKEditor(textarea, config)
                }
            }
        })
    }

    reinitCKEditor(textarea, config) {
        const id = textarea.id
        if (!id) {
            return
        }
        if (window.CKEDITOR.instances[id]) {
            window.CKEDITOR.instances[id].destroy(true)
        }
        config = config || {}
        const new_config = { ...JSON.parse(textarea.getAttribute("data-config")), ...config }
        const editor = window.CKEDITOR.replace(id, new_config)
        this.bindCKEditorDynamicRegionTriggers(editor, textarea)
    }

    bindCKEditorDynamicRegionTriggers(editor, textarea) {
        if (!textarea.hasAttribute('hx-post')) {
            return
        }
        const hxTrigger = textarea.getAttribute('hx-trigger') || 'change'
        const triggerEvents = hxTrigger.split(',').map((part) => part.trim().split(/\s+/)[0]).filter(Boolean)
        const notifyChange = debounce(() => {
            editor.updateElement()
            triggerEvents.forEach((triggerName) => {
                textarea.dispatchEvent(new Event(triggerName, { bubbles: true }))
            })
        }, 300)
        editor.on('change', notifyChange)
        editor.on('blur', () => {
            notifyChange.flush()
        })
    }

    switchCKEditorTheme(target) {
        if (!window.CKEDITOR) {
            return
        }
        if (this.isDarkMode()) {
            this.initCKEditor(target, { 'contentsCss': '/static/sb_admin/css/ckeditor/ckeditor_content_dark.css', uiColor: '#000000' }, true)
            return
        }
        this.initCKEditor(target, { 'contentsCss': window.CKEDITOR.config.contentsCss }, true)
    }

    clearFilter(inputId) {
        const fieldElem = document.querySelector(`#${inputId}`)
        fieldElem.value = ''
        fieldElem.dispatchEvent(new Event('change'))
        fieldElem.dispatchEvent(new CustomEvent('clear', { detail: { refresh: true } }))
    }



    executeListAction(table_id, action_url, no_params, open_in_new_tab = false) {
        if (window.SBAdminTable && window.SBAdminTable[table_id]) {
            window.SBAdminTable[table_id].executeListAction(action_url, no_params, open_in_new_tab)
        } else {
            if (open_in_new_tab) {
                window.open(action_url, '_blank', 'noopener')
            } else {
                window.location.href = action_url
            }
        }
    }
    isCurrentlyCollapsed(parentWrapper) {
        const collapseElements = parentWrapper.querySelectorAll('.js-stacked-inline-collapse')
        return Array.from(collapseElements).every(el => {
            if (el.closest('.djn-empty-form')) {
                return true
            }
            return !el.classList.contains('show')
        })
    }

    updateCollapseAllButton(parentWrapper) {
        const collapseAll = parentWrapper.querySelector('.collapse-all-stacked-inlines')
        if (!collapseAll) return

        const isCollapsed = this.isCurrentlyCollapsed(parentWrapper)
        const expandText = `<svg class="mr-8"><use xlink:href="#View-grid-list"></use></svg><span>${window.sb_admin_translation_strings["expand"]}</span>`
        const collapseText = `<svg class="mr-8"><use xlink:href="#List-checkbox"></use></svg><span>${window.sb_admin_translation_strings["collapse"]}</span>`

        if (isCollapsed) {
            collapseAll.classList.add('collapsed')
            collapseAll.innerHTML = expandText
        } else {
            collapseAll.classList.remove('collapsed')
            collapseAll.innerHTML = collapseText
        }
    }

    initCollapseEventListeners() {
        this.initCollapseAllButtons()

        const debouncedUpdateCollapseAllButton = debounce((parentWrapper) => {
            this.updateCollapseAllButton(parentWrapper)
        }, 50)

        document.addEventListener('shown.bs.collapse', (e) => {
            const parentWrapper = e.target.closest('.djn-fieldset')
            if (parentWrapper && e.target.classList.contains('js-stacked-inline-collapse')) {
                debouncedUpdateCollapseAllButton(parentWrapper)
            }
        })

        document.addEventListener('hidden.bs.collapse', (e) => {
            const parentWrapper = e.target.closest('.djn-fieldset')
            if (parentWrapper && e.target.classList.contains('js-stacked-inline-collapse')) {
                debouncedUpdateCollapseAllButton(parentWrapper)
            }
        })
    }



    initCollapseAllButtons() {
        const collapseAllButtons = document.querySelectorAll('.collapse-all-stacked-inlines')
        collapseAllButtons.forEach(button => {
            const parentWrapper = button.closest('.djn-fieldset')
            if (parentWrapper) {
                this.updateCollapseAllButton(parentWrapper)
            }
        })
    }

    collapseStackedInlineButtons(event) {
        const collapseStackedInline = event.target.closest('.js-collapse-stacked-inline')
        if (collapseStackedInline) {
            const collapseEl = event.target.closest('.djn-inline-form').querySelector('.js-stacked-inline-collapse')
            const instance = Collapse.getOrCreateInstance(collapseEl)
            instance.toggle()
            collapseStackedInline.setAttribute('aria-expanded', collapseStackedInline.getAttribute('aria-expanded') !== 'true')
        }

        const collapseAll = event.target.closest('.collapse-all-stacked-inlines')
        if (collapseAll) {
            event.preventDefault()
            const parentWrapper = collapseAll.closest('.djn-fieldset')
            const collapseElements = parentWrapper.querySelectorAll('.js-stacked-inline-collapse')
            const collapseTriggers = parentWrapper.querySelectorAll('.js-collapse-stacked-inline')
            const isCurrentlyCollapsed = this.isCurrentlyCollapsed(parentWrapper)

            collapseTriggers.forEach(el => {
                if (el.closest('.djn-empty-form')) {
                    return
                }
                if (isCurrentlyCollapsed) {
                    el.setAttribute('aria-expanded', 'true')
                } else {
                    el.setAttribute('aria-expanded', 'false')
                }
            })

            collapseElements.forEach(el => {
                if (el.closest('.djn-empty-form')) {
                    return
                }
                const instance = Collapse.getOrCreateInstance(el)
                if (isCurrentlyCollapsed) {
                    instance.show()
                } else {
                    instance.hide()
                }
            })
        }
    }

    getCopyTarget(button) {
        const selector = button.dataset.sbadminCopySelector
        if (selector) {
            return document.querySelector(selector)
        }
        const targetId = button.dataset.sbadminCopyTarget
        if (targetId) {
            return document.getElementById(targetId)
        }
        return button.closest('.input-affix')?.querySelector('input, textarea, select')
    }

    async writeClipboardText(value) {
        if (window.navigator?.clipboard?.writeText) {
            await window.navigator.clipboard.writeText(value)
            return
        }
        const textarea = document.createElement('textarea')
        textarea.value = value
        textarea.setAttribute('readonly', 'readonly')
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        textarea.remove()
    }

    setCopyButtonLabel(button, label) {
        button.title = label
        button.setAttribute('aria-label', label)
    }

    renderNotification(message, type = 'notice', timeout = NOTIFICATION_AUTO_REMOVE_TIMEOUT) {
        const slot = document.getElementById(NOTIFICATION_SLOT_ID)
        if (!slot || !message) {
            return
        }

        const notificationType = NOTIFICATION_TYPES.has(type) ? type : 'notice'
        const alert = document.createElement('div')
        alert.className = `alert border shadow alert-${notificationType}`
        if (timeout) {
            alert.setAttribute('remove-me', timeout)
        }
        alert.innerHTML = `
            <div class="flex">
                <svg class="alert-icon w-20 h-20 mr-12 shrink-0">
                    <use xlink:href="${notificationType === 'success' ? '#Check-one' : '#Info'}"></use>
                </svg>
                <h5 class="font-semibold"></h5>
                <div class="flex ml-auto items-center">
                    <div class="ml-16 flex-center js-alert-close p-8 -m-8 cursor-pointer group">
                        <svg class="w-20 h-20 group-hover:text-primary">
                            <use xlink:href="#Close"></use>
                        </svg>
                    </div>
                </div>
            </div>
        `
        alert.querySelector('h5').textContent = message
        slot.appendChild(alert)
        window.htmx?.process(alert)
    }

    copyToClipboard(event) {
        const button = event.target.closest(COPY_BUTTON_SELECTOR)
        if (!button) {
            return
        }
        event.preventDefault()

        const target = this.getCopyTarget(button)
        const value = String(target?.value || target?.textContent || '').trim()
        if (!value) {
            return
        }

        this.writeClipboardText(value).then(() => {
            const copyLabel = button.dataset.sbadminCopyLabel || button.title || 'Copy'
            const copiedLabel = button.dataset.sbadminCopiedLabel || 'Copied'
            this.setCopyButtonLabel(button, copiedLabel)
            this.renderNotification(button.dataset.sbadminCopyNotificationLabel || copiedLabel, 'success', '1s')
            window.setTimeout(() => this.setCopyButtonLabel(button, copyLabel), COPIED_TIMEOUT_MS)
        })
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.SBAdmin = new Main()
    window.SBAdminMainLoaded = true
    document.dispatchEvent(new CustomEvent(SBADMIN_MAIN_LOADED_EVENT))
})

document.body.addEventListener('sbadmin:modal-change-form-response', function (event) {
    if (event.detail.reload) {
        window.location.reload()
    }
    if (event.detail.loadUrl) {
        window.location.href = event.detail.loadUrl
    }
})
