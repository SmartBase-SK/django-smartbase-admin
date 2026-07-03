export default class PermissionTree {
    constructor(target) {
        target = target || document
        this.initTrees(target)

        document.addEventListener('change', (e) => this.handleChange(e))
        document.addEventListener('input', (e) => this.handleSearch(e))

        document.addEventListener('formset:added', (event) => {
            this.initTrees(event.target)
        })
        document.addEventListener('htmx:afterSwap', (event) => {
            this.initTrees(event.detail.elt)
        })
        document.addEventListener('htmx:oobAfterSwap', (event) => {
            this.initTrees(event.detail.elt)
        })
    }

    initTrees(target) {
        target.querySelectorAll('[data-permission-tree]').forEach(el => this.initTree(el))
    }

    initTree(container) {
        container.querySelectorAll('[data-permission-tree-checkbox][data-indeterminate="true"]').forEach(cb => {
            cb.indeterminate = true
        })
        this.initBootstrapOverlays(container)
        this.syncHiddenInput(container)
        this.updateCounts(container)
        this.updateEmptyState(container)
    }

    initBootstrapOverlays(container) {
        const Tooltip = window.bootstrap5?.Tooltip || window.bootstrap?.Tooltip
        if (Tooltip) {
            container.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
                const tooltipContainer = el.dataset.bsContainer || container
                Tooltip.getOrCreateInstance(el, {container: tooltipContainer})
            })
        }

        const Popover = window.bootstrap5?.Popover || window.bootstrap?.Popover
        if (Popover) {
            container.querySelectorAll('[data-bs-toggle="popover"]').forEach(el => {
                const popoverContainer = el.dataset.bsContainer || container
                Popover.getOrCreateInstance(el, {container: popoverContainer})
            })
        }
    }

    handleChange(e) {
        const checkbox = e.target.closest('[data-permission-tree-checkbox], [data-permission-tree-select-all]')
        if (!checkbox) return
        const container = checkbox.closest('[data-permission-tree]')
        if (!container) return

        if (checkbox.matches('[data-permission-tree-select-all]')) {
            const appDiv = checkbox.closest('[data-permission-tree-app]')
            appDiv.querySelectorAll('[data-permission-tree-checkbox]').forEach(cb => {
                cb.checked = checkbox.checked
                cb.indeterminate = false
                delete cb.dataset.selectedIds
            })
        } else {
            checkbox.indeterminate = false
            delete checkbox.dataset.selectedIds
        }

        this.updateCounts(container)
        this.syncHiddenInput(container)
    }

    handleSearch(e) {
        const input = e.target.closest('[data-permission-tree-search]')
        if (!input) return
        const container = input.closest('[data-permission-tree]')
        const query = this.normalizeSearchText(input.value.trim())

        container.querySelectorAll('[data-permission-tree-perm]').forEach(perm => {
            const textElements = perm.querySelectorAll('[data-permission-tree-text]')
            const searchText = [
                perm.dataset.permissionTreeSearchText || '',
                ...Array.from(textElements).map(el => this.getRawText(el)),
            ].join(' ')
            const match = !query || this.buildSearchIndex(searchText).text.includes(query)
            perm.hidden = !match
            textElements.forEach(el => {
                const rawText = this.getRawText(el)
                if (match && query) {
                    this.highlightText(el, rawText, query)
                    return
                }
                el.textContent = rawText
            })
        })

        container.querySelectorAll('[data-permission-tree-model]').forEach(m => {
            const visible = Array.from(m.querySelectorAll('[data-permission-tree-perm]')).some(perm => !perm.hidden)
            m.hidden = !visible
            m.querySelectorAll('[data-permission-tree-model-name][data-permission-tree-text]').forEach(el => {
                const rawText = this.getRawText(el)
                if (visible && query && this.buildSearchIndex(rawText).text.includes(query)) {
                    this.highlightText(el, rawText, query)
                    return
                }
                el.textContent = rawText
            })
        })

        container.querySelectorAll('[data-permission-tree-custom-list]').forEach(list => {
            list.hidden = !Array.from(list.querySelectorAll('[data-permission-tree-custom-row]')).some(perm => !perm.hidden)
        })

        container.querySelectorAll('[data-permission-tree-app]').forEach(a => {
            const models = Array.from(a.querySelectorAll('[data-permission-tree-model]'))
            const visiblePerms = Array.from(a.querySelectorAll('[data-permission-tree-perm]')).some(perm => !perm.hidden)
            const visible = models.some(model => !model.hidden) || visiblePerms
            a.hidden = !visible
            if (query && visible) {
                this.showAppCollapse(a)
            }
        })

        this.updateEmptyState(container)
    }

    showAppCollapse(app) {
        const collapseEl = app.querySelector('.collapse')
        const Collapse = window.bootstrap5?.Collapse || window.bootstrap?.Collapse
        if (!collapseEl || !Collapse) return
        Collapse.getOrCreateInstance(collapseEl, {toggle: false}).show()
    }

    updateEmptyState(container) {
        const visibleApps = Array.from(container.querySelectorAll('[data-permission-tree-app]')).filter(app => !app.hidden).length
        const emptyState = container.querySelector('[data-permission-tree-empty]')
        if (emptyState) {
            emptyState.hidden = visibleApps > 0
        }
    }

    getRawText(element) {
        const rawText = element.dataset.raw || element.textContent
        if (!element.dataset.raw) {
            element.dataset.raw = rawText
        }
        return rawText
    }

    normalizeSearchText(value) {
        return String(value)
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
    }

    buildSearchIndex(value) {
        let normalizedText = ''
        const startOffsets = []
        const endOffsets = []
        let offset = 0

        Array.from(value).forEach(char => {
            const start = offset
            offset += char.length
            const normalizedChars = Array.from(this.normalizeSearchText(char))

            normalizedChars.forEach(normalizedChar => {
                normalizedText += normalizedChar
                startOffsets.push(start)
                endOffsets.push(offset)
            })
        })

        return {
            text: normalizedText,
            startOffsets: startOffsets,
            endOffsets: endOffsets,
        }
    }

    escapeHTML(value) {
        return value.replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[char]))
    }

    highlightText(element, rawText, query) {
        const searchIndex = this.buildSearchIndex(rawText)
        let offset = 0
        let html = ''
        let searchOffset = 0
        let matchIndex = searchIndex.text.indexOf(query, searchOffset)

        while (matchIndex !== -1) {
            const start = searchIndex.startOffsets[matchIndex]
            const end = searchIndex.endOffsets[matchIndex + query.length - 1]
            html += this.escapeHTML(rawText.slice(offset, start))
            html += '<mark>' + this.escapeHTML(rawText.slice(start, end)) + '</mark>'
            offset = end
            searchOffset = matchIndex + query.length
            matchIndex = searchIndex.text.indexOf(query, searchOffset)
        }

        html += this.escapeHTML(rawText.slice(offset))
        element.innerHTML = html
    }

    updateCounts(container) {
        container.querySelectorAll('[data-permission-tree-app]').forEach(appDiv => {
            const checkboxes = appDiv.querySelectorAll('[data-permission-tree-checkbox]')
            const checked = appDiv.querySelectorAll('[data-permission-tree-checkbox]:checked')
            const partiallyChecked = Array.from(checkboxes).filter(cb => cb.indeterminate)
            const countEl = appDiv.querySelector('[data-permission-tree-count]')
            if (countEl) {
                countEl.textContent = checked.length + '/' + checkboxes.length
            }

            const selectAll = appDiv.querySelector('[data-permission-tree-select-all]')
            if (selectAll) {
                if (checked.length === 0) {
                    selectAll.checked = false
                    selectAll.indeterminate = partiallyChecked.length > 0
                } else if (checked.length === checkboxes.length) {
                    selectAll.checked = true
                    selectAll.indeterminate = false
                } else {
                    selectAll.checked = false
                    selectAll.indeterminate = true
                }
            }
        })
    }

    syncHiddenInput(container) {
        const checked = new Set()
        container.querySelectorAll('[data-permission-tree-checkbox]').forEach(cb => {
            if (cb.checked) {
                this.permissionIdsForCheckbox(cb).forEach(id => checked.add(id))
                return
            }
            if (cb.indeterminate && cb.dataset.selectedIds) {
                this.parseIds(cb.dataset.selectedIds).forEach(id => checked.add(id))
            }
        })
        const hidden = container.querySelector('[data-permission-tree-value]')
        if (hidden) {
            hidden.value = JSON.stringify(Array.from(checked))
        }
    }

    permissionIdsForCheckbox(checkbox) {
        if (checkbox.dataset.permIds) {
            return this.parseIds(checkbox.dataset.permIds)
        }
        const value = parseInt(checkbox.value, 10)
        return Number.isNaN(value) ? [] : [value]
    }

    parseIds(value) {
        try {
            const ids = JSON.parse(value)
            if (!Array.isArray(ids)) return []
            return ids.map(id => parseInt(id, 10)).filter(id => !Number.isNaN(id))
        } catch {
            return []
        }
    }
}

const initPermissionTree = () => {
    if (window.SBAdminPermissionTree) return
    window.SBAdminPermissionTree = new PermissionTree()
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPermissionTree, {once: true})
} else {
    initPermissionTree()
}
