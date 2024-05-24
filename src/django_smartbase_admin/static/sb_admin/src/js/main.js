import Dropdown from 'bootstrap/js/dist/dropdown'
import Collapse from 'bootstrap/js/dist/collapse'
import Tab from 'bootstrap/js/dist/tab'
import Modal from 'bootstrap/js/dist/modal'
import Tooltip from 'bootstrap/js/dist/tooltip'

// remove Modal focus trap to fix interaction with fields in modals inside another modal
Modal.prototype._initializeFocusTrap = function () { return { activate: function () { }, deactivate: function () { } } }

window.bootstrap5 = {
    Modal: Modal,
    Tooltip: Tooltip,
    Collapse: Collapse,
    Tab: Tab,
    Dropdown: Dropdown
}

import Sidebar from "./sidebar"
import Datepicker from "./datepicker"
import Range from "./range"
import Sorting from "./sorting"
import Autocomplete from "./autocomplete"
import ChoicesJS from "./choices"
import {setCookie} from "./utils"
import Multiselect from "./multiselect"

class Main {
    constructor() {
        document.body.classList.add('js-ready')

        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
        tooltipTriggerList.map((tooltipTriggerEl) => {
            const tooltipEl = tooltipTriggerEl.closest('.js-tooltip')
            if(tooltipEl) {
                return new Tooltip(tooltipTriggerEl, {container: tooltipEl})
            }
            return null
        })

        this.initDropdowns()
        document.addEventListener('formset:added', (e) => {
            this.initDropdowns(e.target)
            this.initFileInputs(e.target)
            if (e.target !== e.target.parentNode.firstChild) {
                e.target.parentNode.insertBefore(e.target, e.target.parentNode.firstChild)
            }
        })
        document.addEventListener('openUrl', (e) => {
            window.open(e.detail.url, e.detail?.target || '_blank')
        })

        new Sidebar()
        this.datepicker = new Datepicker()
        this.range = new Range()
        new Sorting()
        this.autocomplete = new Autocomplete()
        new ChoicesJS()
        this.multiselect = new Multiselect()
        document.addEventListener('click', (e) => {
            this.closeAlert(e)
            this.selectAll(e)
            this.saveState(e)
            this.fileDownload(e)
            this.passwordToggleFnc(e)
        })
        this.initFileInputs()
        this.initAliasName()
        this.handleLocationHashFromTabs()
    }

    handleLocationHashFromTabs() {
        if(window.location.hash) {
            document.querySelector(`#tab_${window.location.hash.slice(1)}`)?.click()
        }
        const tabEls = document.querySelectorAll('button[data-bs-toggle="tab"]:not([data-bs-disable-history])')
        tabEls.forEach(tab => {
            tab.addEventListener('shown.bs.tab', function (event) {
                window.location.hash = event.target.id.split("tab_")[1]
            })
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
        if(button) {
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
        const dropdowns = [].slice.call(target.querySelectorAll('[data-bs-toggle="dropdown"]'))
        dropdowns.map((dropdownToggleEl) => {
            let offset = dropdownToggleEl.dataset['bsOffset']
            if(offset) {
                offset = JSON.parse(dropdownToggleEl.dataset['bsOffset'])
            }
            else {
                offset = [0,8]
            }
            return new Dropdown(dropdownToggleEl, {
                autoClose: 'outside',
                offset: offset,
                popperConfig(defaultBsPopperConfig) {
                    const elementConf = {}
                    if(dropdownToggleEl.dataset['bsPopperPlacement']) {
                        elementConf['placement'] = dropdownToggleEl.dataset['bsPopperPlacement']
                    }
                    return { ...defaultBsPopperConfig, ...elementConf, strategy: 'fixed' }
                }
            })
        })
    }

    initAliasName() {
        const aliasGroup = document.getElementById(window.sb_admin_const.GLOBAL_FILTER_ALIAS_WIDGET_ID)
        if(!aliasGroup) {
            return
        }

        const changeAliasName = () => {
            const currentAlias = aliasGroup.querySelector('input[name="alias"]:checked')
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
            if(isBsToggle === 'collapse') {
                const expanded = saveStateEl.getAttribute('aria-expanded') === 'true'
                setCookie(saveStateEl.id, expanded, expanded?1:0)
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

        if(wrapper) {
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
                if(delete_checkbox) {
                    delete_checkbox.checked = false
                }
                if(e.target.files[0]) {
                    fileInput.classList.add('filled')
                    fileInput.querySelectorAll('.js-input-file-image').forEach(el => {
                        el.src = URL.createObjectURL(e.target.files[0])
                    })
                    fileInput.querySelector('.js-input-file-filename').innerHTML = e.target.files[0].name
                }
                else {
                    fileInput.classList.remove('filled')
                    fileInput.querySelector('.js-input-file-filename').innerHTML = ""
                }
            })

            const deleteButton = fileInput.querySelector('.js-input-file-delete')
            deleteButton?.addEventListener('click', () => {
                input.value = ""
                input.dispatchEvent(new Event('change'))
                if(delete_checkbox) {
                    delete_checkbox.checked = true
                }
            })
        })
    }

    clearFilter(inputId) {
        const fieldElem = document.querySelector(`#${inputId}`)
        fieldElem.value = ''
        fieldElem.dispatchEvent(new Event('change'))
        fieldElem.dispatchEvent(new CustomEvent('clear', {detail: {refresh: true}}))
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.SBAdmin = new Main()
    window.dispatchEvent(new CustomEvent("SBAdminLoaded"))
})
