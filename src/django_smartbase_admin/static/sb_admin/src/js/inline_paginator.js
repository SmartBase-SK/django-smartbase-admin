class InlinePaginator {
    constructor() {
        this.configs = {}
        this.boundPrefixes = new Set()
    }

    init(config) {
        if (!config.prefix) return
        const translations = window.sb_admin_translation_strings || {}
        const previousState = this.configs[config.prefix] || {}

        const state = {
            unsavedChangesTitle: translations.inline_paginator_unsaved_title || 'Unsaved changes',
            unsavedChangesMessage: (
                translations.inline_paginator_unsaved_message
                || 'This list has unsaved changes. Changing page will discard them.'
            ),
            unsavedChangesSubmit: translations.inline_paginator_continue || translations.confirm || 'Continue',
            unsavedChangesCancel: translations.cancel || 'Cancel',
            ...config,
            paginationClass: `pagination-plus-${config.prefix}`,
            searchClass: `inline-search-plus-${config.prefix}`,
            searchMode: config.searchMode || 'server',
            confirmEventName: `sbadminInlinePaginationConfirmed:${config.prefix}`,
            cancelEventName: `sbadminInlinePaginationCancelled:${config.prefix}`,
            inlineGroupId: `${config.prefix}-group`,
            confirmedPaginationTarget: previousState.confirmedPaginationTarget || null,
            pendingSearchFocus: previousState.pendingSearchFocus || null,
        }
        this.configs[config.prefix] = state
        this.resetDirtyFlag(state)
        this.bindClientSearch(config.prefix)

        if (this.boundPrefixes.has(config.prefix)) return
        this.boundPrefixes.add(config.prefix)

        document.body.addEventListener('input', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('change', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('SBAutocompleteChange', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('formset:added', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener(state.confirmEventName, () => this.confirmPagination(config.prefix))
        document.body.addEventListener(state.cancelEventName, () => this.cancelPagination(config.prefix))
        document.body.addEventListener('htmx:configRequest', event => this.handleConfigRequest(config.prefix, event))
        document.body.addEventListener('htmx:afterSettle', () => this.restoreSearchFocus(config.prefix))
    }

    getState(prefix) {
        return this.configs[prefix]
    }

    getInlineGroup(state) {
        return document.getElementById(state.inlineGroupId)
    }

    resetDirtyFlag(state) {
        const group = this.getInlineGroup(state)
        if (!group) return
        group.dataset.sbadminInlineDirty = ''
    }

    hasUnsavedChanges(state) {
        const group = this.getInlineGroup(state)
        if (!group) return false
        return group.dataset.sbadminInlineDirty === 'true'
    }

    markUnsavedChanges(prefix, event) {
        const state = this.getState(prefix)
        if (!state) return
        const group = this.getInlineGroup(state)
        if (!group || !group.contains(event.target)) return
        if (event.target.classList?.contains(state.searchClass)) return

        group.dataset.sbadminInlineDirty = 'true'
        const cell = event.target.closest?.('.djn-td')
        if (cell && group.contains(cell)) {
            cell.dataset.sbadminInlineDirtyCell = 'true'
            return
        }

        const row = event.target.closest?.('.djn-inline-form')
        row?.querySelectorAll('.djn-td').forEach(cell => {
            cell.dataset.sbadminInlineDirtyCell = 'true'
        })
    }

    highlightDirtyCells(state) {
        const group = this.getInlineGroup(state)
        if (!group) return
        group.querySelectorAll("[data-sbadmin-inline-dirty-cell='true']").forEach(cell => {
            this.restartClassAnimation(cell, 'sbadmin-inline-dirty-cell')
        })
    }

    highlightContinueButton() {
        document.querySelectorAll('[name="_continue"]').forEach(button => {
            this.restartClassAnimation(button, 'sbadmin-inline-dirty-continue')
        })
    }

    restartClassAnimation(element, className) {
        element.classList.remove(className)
        window.requestAnimationFrame(() => {
            element.classList.add(className)
        })
    }

    highlightUnsavedChanges(state) {
        this.highlightDirtyCells(state)
        this.highlightContinueButton()
    }

    showUnsavedChangesConfirmation(state, target) {
        if (!window.Confirmation || !window.Confirmation.modal) {
            const confirmed = window.confirm(`${state.unsavedChangesTitle}\n\n${state.unsavedChangesMessage}`)
            if (!confirmed) {
                this.highlightUnsavedChanges(state)
            }
            return confirmed
        }

        state.confirmedPaginationTarget = target
        const trigger = document.createElement('button')
        trigger.dataset.confirmBody = (
            `<h3 class='mb-8 font-semibold w-full text-18 text-center text-dark-900 leading-28'>`
            + `${state.unsavedChangesTitle}</h3>`
            + `<p class='w-full text-center text-14 leading-20 text-dark-700'>`
            + `${state.unsavedChangesMessage}</p>`
        )
        trigger.dataset.confirmSubmit = state.unsavedChangesSubmit
        trigger.dataset.confirmClose = state.unsavedChangesCancel
        trigger.dataset.submitEvent = state.confirmEventName
        trigger.dataset.cancelEvent = state.cancelEventName
        trigger.dataset.responseTarget = 'body'
        window.Confirmation.updateModalData(trigger)
        window.Confirmation.updateModalContent()
        window.Confirmation.modal.show()
        return false
    }

    normalizeSearchValue(value) {
        return (value || '')
            .toString()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
    }

    applyClientSearch(state, term) {
        const group = this.getInlineGroup(state)
        if (!group) return
        const normalizedTerm = this.normalizeSearchValue(term)
        const rows = group.querySelectorAll('.djn-tbody')
        rows.forEach(row => {
            if (row.classList.contains('empty-form')) return
            const rowText = this.normalizeSearchValue(row.textContent)
            const isMatch = !normalizedTerm || rowText.includes(normalizedTerm)
            row.style.display = isMatch ? '' : 'none'
        })
    }

    bindClientSearch(prefix) {
        const state = this.getState(prefix)
        if (!state || state.searchMode !== 'client') return
        const input = document.querySelector(`.${state.searchClass}`)
        if (!input || input.dataset.sbadminInlineSearchBound === 'true') return
        input.dataset.sbadminInlineSearchBound = 'true'
        const applyFilter = event => this.applyClientSearch(state, event.target.value)
        input.addEventListener('input', applyFilter)
        input.addEventListener('search', applyFilter)
        this.applyClientSearch(state, input.value)
    }

    scheduleSearchFocusRestore(state, inputElement) {
        state.pendingSearchFocus = {
            value: inputElement.value,
            selectionStart: inputElement.selectionStart,
            selectionEnd: inputElement.selectionEnd,
        }
    }

    restoreSearchFocus(prefix) {
        const state = this.getState(prefix)
        if (!state || !state.pendingSearchFocus) return
        const input = document.querySelector(`.${state.searchClass}`)
        if (!input) return

        const { value, selectionStart, selectionEnd } = state.pendingSearchFocus
        if (input.value !== value) {
            state.pendingSearchFocus = null
            return
        }

        input.focus({ preventScroll: true })
        if (
            typeof selectionStart === 'number'
            && typeof selectionEnd === 'number'
            && typeof input.setSelectionRange === 'function'
        ) {
            input.setSelectionRange(selectionStart, selectionEnd)
        }
        state.pendingSearchFocus = null
    }

    confirmPagination(prefix) {
        const state = this.getState(prefix)
        if (!state || !state.confirmedPaginationTarget) return
        const target = state.confirmedPaginationTarget
        state.confirmedPaginationTarget = null
        target.dataset.sbadminInlinePaginationConfirmed = 'true'
        if (target.classList.contains(state.searchClass)) {
            if (window.htmx && typeof window.htmx.trigger === 'function') {
                window.htmx.trigger(target, 'change')
                return
            }
            target.dispatchEvent(new Event('change', { bubbles: true }))
            return
        }
        target.click()
    }

    cancelPagination(prefix) {
        const state = this.getState(prefix)
        if (!state) return
        state.confirmedPaginationTarget = null
        this.highlightUnsavedChanges(state)
    }

    hasParameter(parameters, key) {
        if (typeof parameters.has === 'function') {
            return parameters.has(key)
        }
        return Object.prototype.hasOwnProperty.call(parameters, key)
    }

    setParameter(parameters, key, value) {
        if (typeof parameters.set === 'function') {
            parameters.set(key, value)
            return
        }
        parameters[key] = value
    }

    handleConfigRequest(prefix, event) {
        const state = this.getState(prefix)
        if (
            !state
            || (
                !event.target.classList.contains(state.paginationClass)
                && !event.target.classList.contains(state.searchClass)
            )
        ) return
        if (event.target.dataset.sbadminInlinePaginationConfirmed === 'true') {
            delete event.target.dataset.sbadminInlinePaginationConfirmed
        } else if (
            this.hasUnsavedChanges(state)
            && !this.showUnsavedChangesConfirmation(state, event.target)
        ) {
            event.preventDefault()
            return
        }

        if (event.target.classList.contains(state.searchClass)) {
            this.scheduleSearchFocusRestore(state, event.target)
        }

        const url = new URL(window.location.href)
        url.searchParams.forEach((value, key) => {
            if (!this.hasParameter(event.detail.parameters, key)) {
                this.setParameter(event.detail.parameters, key, value)
            }
        })
        url.search = ''
        event.detail.path = url.href
    }
}

const inlinePaginator = new InlinePaginator()
window.SBAdminInlinePaginator = inlinePaginator

const queuedConfigs = window.SBAdminInlinePaginatorQueue || []
queuedConfigs.forEach(config => {
    inlinePaginator.init(config)
})
window.SBAdminInlinePaginatorQueue = []

export default inlinePaginator
