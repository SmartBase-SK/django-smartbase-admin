class InlinePaginator {
    constructor() {
        this.configs = {}
        this.boundPrefixes = new Set()
    }

    init(config) {
        if (!config.prefix) return
        const translations = window.sb_admin_translation_strings || {}

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
            confirmEventName: `sbadminInlinePaginationConfirmed:${config.prefix}`,
            cancelEventName: `sbadminInlinePaginationCancelled:${config.prefix}`,
            inlineGroupId: `${config.prefix}-group`,
            confirmedPaginationTarget: null,
        }
        this.configs[config.prefix] = state
        this.resetDirtyFlag(state)

        if (this.boundPrefixes.has(config.prefix)) return
        this.boundPrefixes.add(config.prefix)

        document.body.addEventListener('input', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('change', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('SBAutocompleteChange', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener('formset:added', event => this.markUnsavedChanges(config.prefix, event), true)
        document.body.addEventListener(state.confirmEventName, () => this.confirmPagination(config.prefix))
        document.body.addEventListener(state.cancelEventName, () => this.cancelPagination(config.prefix))
        document.body.addEventListener('htmx:configRequest', event => this.handleConfigRequest(config.prefix, event))
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

    confirmPagination(prefix) {
        const state = this.getState(prefix)
        if (!state || !state.confirmedPaginationTarget) return
        const target = state.confirmedPaginationTarget
        state.confirmedPaginationTarget = null
        target.dataset.sbadminInlinePaginationConfirmed = 'true'
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
        if (!state || !event.target.classList.contains(state.paginationClass)) return

        if (event.target.dataset.sbadminInlinePaginationConfirmed === 'true') {
            delete event.target.dataset.sbadminInlinePaginationConfirmed
        } else if (
            this.hasUnsavedChanges(state)
            && !this.showUnsavedChangesConfirmation(state, event.target)
        ) {
            event.preventDefault()
            return
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
