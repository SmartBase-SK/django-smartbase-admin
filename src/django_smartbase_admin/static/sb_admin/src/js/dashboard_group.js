import {ensureFilterForm, filterInputValueChangeListener, filterInputValueChangedUtil} from "./utils"

class SBAdminDashboardGroup {
    constructor(element) {
        this.element = element
        this.groupId = element.dataset.dashboardGroupId
        this.formId = element.dataset.filterFormId
        this.ajaxUrl = element.dataset.ajaxUrl
        this.subWidgets = new Map()
        this.lastData = null
        this.refreshCount = 0
        this.initialized = false
        this.listeningFormIds = new Set()
    }

    filterFormIds() {
        const formIds = new Set([this.formId])
        this.subWidgets.forEach((definition) => {
            if (definition.formId) {
                formIds.add(definition.formId)
            }
        })
        return formIds
    }

    formValues() {
        const values = {}
        this.filterFormIds().forEach((formId) => {
            ensureFilterForm(formId)
            const form = document.getElementById(formId)
            const entries = form ? new FormData(form).entries() : new FormData().entries()
            for (const [key, value] of entries) {
                if (value) {
                    values[key] = value
                }
            }
        })
        return values
    }

    updateSubWidget(definition, responseData, isInitialData = false) {
        if (isInitialData && definition.skipInitialData) {
            return
        }
        const widgetData = responseData.sub_widget[definition.widgetId]
        if (!widgetData || !definition.onData) {
            return
        }
        definition.onData(widgetData)
    }

    refresh() {
        const isInitialData = this.refreshCount === 0
        fetch(`${this.ajaxUrl}?${new URLSearchParams(this.formValues())}`, {
            method: 'GET',
            headers: {"X-CSRFToken": window.csrf_token},
        }).then(response => response.json()).then(response => {
            this.lastData = response.data
            this.refreshCount += 1
            this.subWidgets.forEach((definition) => {
                this.updateSubWidget(definition, this.lastData, isInitialData)
            })
        })
    }

    registerSubWidget(definition) {
        this.subWidgets.set(definition.widgetId, definition)
        if (this.initialized && definition.formId) {
            this.listenToFilterForm(definition.formId)
        }
        if (this.lastData) {
            this.updateSubWidget(definition, this.lastData, this.refreshCount === 1)
        }
    }

    listenToFilterForm(formId) {
        if (!formId || this.listeningFormIds.has(formId)) {
            return
        }
        this.listeningFormIds.add(formId)
        ensureFilterForm(formId)
        filterInputValueChangeListener(`[form="${formId}"]`, (event) => {
            this.refresh()
            filterInputValueChangedUtil(event.target)
        })
    }

    init() {
        if (this.initialized) {
            return
        }
        this.initialized = true
        this.refresh()

        document.addEventListener(window.sb_admin_const.TABLE_RELOAD_DATA_EVENT_NAME, () => {
            this.refresh()
        })
        this.filterFormIds().forEach((formId) => {
            this.listenToFilterForm(formId)
        })
    }
}

const registeredSubWidgets = new Map()

function getRegisteredSubWidgets(groupId) {
    if (!registeredSubWidgets.has(groupId)) {
        registeredSubWidgets.set(groupId, new Map())
    }
    return registeredSubWidgets.get(groupId)
}

function initDashboardGroups() {
    window.SBAdminDashboardGroups = window.SBAdminDashboardGroups || {}
    document.querySelectorAll('[data-dashboard-group-id]').forEach((element) => {
        const groupId = element.dataset.dashboardGroupId
        if (window.SBAdminDashboardGroups[groupId]) {
            return
        }
        const group = new SBAdminDashboardGroup(element)
        // Child widgets usually register while the group HTML is rendering.
        // Init copies those callbacks into the live group before the first shared AJAX refresh.
        getRegisteredSubWidgets(group.groupId).forEach((definition) => {
            group.registerSubWidget(definition)
        })
        window.SBAdminDashboardGroups[groupId] = group
        group.init()
    })
}

function initDashboardGroupsOnReady() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDashboardGroups, {once: true})
        return
    }
    initDashboardGroups()
}

window.SBAdminRegisterDashboardSubWidget = function(groupId, definition) {
    // Keep every child callback in the registration map so init can wire it once the group exists.
    getRegisteredSubWidgets(groupId).set(definition.widgetId, definition)
    const group = window.SBAdminDashboardGroups && window.SBAdminDashboardGroups[groupId]
    if (group) {
        // Some widgets, especially tables, initialize after the group. Attach them immediately too.
        // registerSubWidget de-duplicates by widgetId through the group's Map.
        group.registerSubWidget(definition)
    }
}
window.SBAdminInitDashboardGroups = initDashboardGroups
initDashboardGroupsOnReady()
