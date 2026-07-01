export default class PermissionTree {
    constructor(target) {
        target = target || document
        this.initTrees(target)

        document.addEventListener('change', (e) => this.handleChange(e))
        document.addEventListener('input', (e) => this.handleSearch(e))
        document.addEventListener('click', (e) => this.handleToggle(e))

        document.addEventListener('formset:added', (event) => {
            this.initTrees(event.target)
        })
    }

    initTrees(target) {
        target.querySelectorAll('.permission-tree').forEach(el => this.initTree(el))
    }

    initTree(container) {
        this.syncHiddenInput(container)
        this.updateCounts(container)
    }

    handleChange(e) {
        const checkbox = e.target.closest('.permission-tree__checkbox, .permission-tree__select-all')
        if (!checkbox) return
        const container = checkbox.closest('.permission-tree')
        if (!container) return

        if (checkbox.classList.contains('permission-tree__select-all')) {
            const modelDiv = checkbox.closest('.permission-tree__model')
            modelDiv.querySelectorAll('.permission-tree__checkbox').forEach(cb => {
                cb.checked = checkbox.checked
            })
        }

        this.updateCounts(container)
        this.syncHiddenInput(container)
    }

    handleSearch(e) {
        const input = e.target.closest('.permission-tree__search-input')
        if (!input) return
        const container = input.closest('.permission-tree')
        const query = input.value.toLowerCase().trim()

        container.querySelectorAll('.permission-tree__perm').forEach(perm => {
            const nameEl = perm.querySelector('.permission-tree__perm-name')
            const rawText = nameEl.dataset.raw || nameEl.textContent
            if (!nameEl.dataset.raw) {
                nameEl.dataset.raw = rawText
            }
            const match = !query || rawText.toLowerCase().includes(query)
            perm.style.display = match ? '' : 'none'
            if (match && query) {
                const idx = rawText.toLowerCase().indexOf(query)
                if (idx >= 0) {
                    nameEl.innerHTML = rawText.slice(0, idx) + '<mark>' + rawText.slice(idx, idx + query.length) + '</mark>' + rawText.slice(idx + query.length)
                    return
                }
            }
            nameEl.innerHTML = rawText
        })

        container.querySelectorAll('.permission-tree__model').forEach(m => {
            const visible = m.querySelectorAll('.permission-tree__perm[style*="display"]:not([style*="display: none"])').length > 0
            m.style.display = visible ? '' : 'none'
        })

        container.querySelectorAll('.permission-tree__app').forEach(a => {
            const visible = a.querySelectorAll('.permission-tree__model[style*="display"]:not([style*="display: none"])').length > 0
            a.style.display = visible ? '' : 'none'
        })
    }

    handleToggle(e) {
        const btn = e.target.closest('.permission-tree__app-toggle')
        if (!btn) return
        e.preventDefault()
        const expanded = btn.getAttribute('aria-expanded') === 'true'
        btn.setAttribute('aria-expanded', expanded ? 'false' : 'true')
    }

    updateCounts(container) {
        container.querySelectorAll('.permission-tree__model').forEach(modelDiv => {
            const checkboxes = modelDiv.querySelectorAll('.permission-tree__checkbox')
            const checked = modelDiv.querySelectorAll('.permission-tree__checkbox:checked')
            const countEl = modelDiv.querySelector('.permission-tree__count')
            if (countEl) {
                countEl.textContent = checked.length + '/' + checkboxes.length
            }

            const selectAll = modelDiv.querySelector('.permission-tree__select-all')
            if (selectAll) {
                if (checked.length === 0) {
                    selectAll.checked = false
                    selectAll.indeterminate = false
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
        const checked = []
        container.querySelectorAll('.permission-tree__checkbox:checked').forEach(cb => {
            checked.push(parseInt(cb.value, 10))
        })
        const hidden = container.querySelector('.permission-tree__value')
        if (hidden) {
            hidden.value = JSON.stringify(checked)
        }
    }
}
