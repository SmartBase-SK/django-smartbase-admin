/**
 * Dynamic formset rows for SBAdmin (used in wizards and other views).
 * Clones markup from <template> and replaces __prefix__ with the row index.
 */

import {shouldProcessAfterSwap} from './utils'

const FORMSET_SELECTOR = '.sbadmin-formset-dynamic'
const ROW_SELECTOR = '.sbadmin-formset-row'
const DELETE_ROW_SELECTOR = '[data-sbadmin-formset-delete-row]'
const INIT_ATTR = 'data-sbadmin-formset-initialized'

export default class SBAdminFormset {
    constructor() {
        this.handleClick = this.handleClick.bind(this)
        document.addEventListener('click', this.handleClick)
        this.initHtmxListeners()
        this.run(document)
    }

    processAfterSwap(target) {
        if (!target || typeof target.querySelectorAll !== 'function') {
            this.run(document)
            return
        }
        this.run(target)
    }

    initHtmxListeners() {
        if (!window.htmx) {
            return
        }
        window.htmx.on('htmx:afterSwap', (event) => {
            if (!shouldProcessAfterSwap(event)) {
                return
            }
            this.processAfterSwap(event.target)
        })
        window.htmx.on('htmx:oobAfterSwap', (event) => {
            const target = event.detail?.elt || event.detail?.target || event.target
            if (!target) {
                return
            }
            this.processAfterSwap(target)
        })
    }

    static replacePrefix(root, index) {
        const idx = String(index)
        const nodes = [root]
        const q = root.querySelectorAll('*')
        for (let i = 0; i < q.length; i++) nodes.push(q[i])
        for (let n = 0; n < nodes.length; n++) {
            const el = nodes[n]
            if (!el.attributes) continue
            for (let a = 0; a < el.attributes.length; a++) {
                const attr = el.attributes[a]
                if (attr.value.indexOf('__prefix__') !== -1) {
                    el.setAttribute(attr.name, attr.value.replace(/__prefix__/g, idx))
                }
            }
        }
    }

    initFormset(container) {
        if (container.getAttribute(INIT_ATTR) === '1') {
            return
        }
        const prefix = container.getAttribute('data-prefix')
        if (!prefix) return
        const maxForms = parseInt(container.getAttribute('data-max-forms') || '1000', 10)
        const totalInput = container.querySelector(
            `input[name="${prefix}-TOTAL_FORMS"]`
        )
        const formsWrap = container.querySelector('.sbadmin-formset-forms')
        const tpl = document.getElementById(`${prefix}-empty-template`)
        const addBtn = container.querySelector('.sbadmin-formset-add')
        if (!totalInput || !formsWrap || !tpl || !tpl.content || !addBtn) return

        addBtn.addEventListener('click', (e) => {
            e.preventDefault()
            const total = parseInt(totalInput.value, 10)
            if (isNaN(total) || total >= maxForms) return
            const row = tpl.content.firstElementChild.cloneNode(true)
            if (!row) return
            SBAdminFormset.replacePrefix(row, total)
            row.id = `${prefix}-${total}`
            row.removeAttribute('data-sbadmin-formset-initial-row')
            row.style.order = total
            row.querySelectorAll("script:not([type='application/json'])").forEach((s) => {
                s.remove()
            })
            formsWrap.appendChild(row)
            totalInput.value = total + 1
            this.syncDeleteButtons(container)
            row.dispatchEvent(
                new CustomEvent('formset:added', {
                    bubbles: true,
                    detail: { formsetName: prefix },
                })
            )
        })
        container.setAttribute(INIT_ATTR, '1')
    }

    getVisibleRows(formsWrap) {
        if (!formsWrap) return []
        return Array.prototype.slice.call(
            formsWrap.querySelectorAll(`${ROW_SELECTOR}:not(.hidden)`)
        )
    }

    syncDeleteButtons(formset) {
        if (!formset) return
        const formsWrap = formset.querySelector('.sbadmin-formset-forms')
        let protectedRows = parseInt(
            formset.getAttribute('data-delete-protected-rows') || '0',
            10
        )
        if (isNaN(protectedRows)) protectedRows = 0
        const visibleRows = this.getVisibleRows(formsWrap)
        const protectedVisibleInitialRows = visibleRows
            .filter((row) => row.hasAttribute('data-sbadmin-formset-initial-row'))
            .slice(0, protectedRows)
        visibleRows.forEach((row) => {
            const isProtected = protectedVisibleInitialRows.indexOf(row) !== -1
            row.querySelectorAll(DELETE_ROW_SELECTOR).forEach((button) => {
                button.classList.toggle('hidden', isProtected)
                button.hidden = isProtected
            })
        })
    }

    deleteFormsetRow(button) {
        const row = button.closest(ROW_SELECTOR)
        if (!row) return
        const formset = row.closest(FORMSET_SELECTOR)
        const formsWrap = row.closest('.sbadmin-formset-forms')
        let minForms = parseInt(
            formset ? formset.getAttribute('data-min-forms') || '0' : '0',
            10
        )
        if (isNaN(minForms)) minForms = 0
        const visibleRows = this.getVisibleRows(formsWrap)
        if (visibleRows.length <= minForms) return

        const deleteInput = row.querySelector('input[type="checkbox"][name$="-DELETE"]')
        if (deleteInput) {
            deleteInput.checked = true
        }
        row.classList.add('hidden')
        this.syncDeleteButtons(formset)
    }

    handleClick(event) {
        const deleteButton = event.target.closest(DELETE_ROW_SELECTOR)
        if (!deleteButton) return
        event.preventDefault()
        this.deleteFormsetRow(deleteButton)
    }

    run(scope) {
        const root =
            scope && typeof scope.querySelectorAll === 'function' ? scope : document
        root.querySelectorAll(FORMSET_SELECTOR).forEach((formset) => {
            this.initFormset(formset)
            this.syncDeleteButtons(formset)
        })
    }
}

window.SBAdminFormsetClass = SBAdminFormset

const startSBAdminFormset = () => {
    window.SBAdminFormset = new SBAdminFormset()
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startSBAdminFormset)
} else {
    startSBAdminFormset()
}
