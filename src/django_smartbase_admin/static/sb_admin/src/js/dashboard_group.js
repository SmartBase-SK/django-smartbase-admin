import {filterInputValueChangeListener, filterInputValueChangedUtil} from "./utils"

class SBAdminDashboardGroup {
    constructor(element) {
        this.element = element
        this.groupId = element.dataset.dashboardGroupId
        this.formId = element.dataset.filterFormId
        this.ajaxUrl = element.dataset.ajaxUrl
        this.subWidgets = {}
        this.lastData = null
        this.initialized = false
    }

    formValues() {
        const values = {}
        const form = document.getElementById(this.formId)
        const entries = form ? new FormData(form).entries() : new FormData()
        for (const [key, value] of entries) {
            if (value) {
                values[key] = value
            }
        }
        if (!form) {
            document.querySelectorAll(`[form="${this.formId}"]`).forEach((input) => {
                if (input.name && input.value) {
                    values[input.name] = input.value
                }
            })
        }
        return values
    }

    updateSubWidget(definition, responseData) {
        const widgetData = responseData.sub_widget[definition.widgetId]
        if (!widgetData || !definition.onData) {
            return
        }
        definition.onData(widgetData)
    }

    refresh() {
        fetch(`${this.ajaxUrl}?${new URLSearchParams(this.formValues())}`, {
            method: 'GET',
            headers: {"X-CSRFToken": window.csrf_token},
        }).then(response => response.json()).then(response => {
            this.lastData = response.data
            Object.values(this.subWidgets).forEach((definition) => {
                this.updateSubWidget(definition, this.lastData)
            })
        })
    }

    registerSubWidget(definition) {
        this.subWidgets[definition.widgetId] = definition
        if (this.lastData) {
            this.updateSubWidget(definition, this.lastData)
        }
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
        filterInputValueChangeListener(`[form="${this.formId}"]`, (event) => {
            this.refresh()
            filterInputValueChangedUtil(event.target)
        })
    }
}

function initDashboardGroups() {
    window.SBAdminDashboardGroups = window.SBAdminDashboardGroups || {}
    document.querySelectorAll('[data-dashboard-group-id]').forEach((element) => {
        const groupId = element.dataset.dashboardGroupId
        const group = window.SBAdminDashboardGroups[groupId] || new SBAdminDashboardGroup(element)
        window.SBAdminDashboardGroups[groupId] = group
        const pendingDefinitions = window.SBAdminDashboardGroupPendingSubWidgets[groupId] || []
        pendingDefinitions.forEach((definition) => {
            group.registerSubWidget(definition)
        })
        window.SBAdminDashboardGroupPendingSubWidgets[groupId] = []
        group.init()
    })
}

window.SBAdminDashboardGroups = window.SBAdminDashboardGroups || {}
window.SBAdminDashboardGroupPendingSubWidgets = window.SBAdminDashboardGroupPendingSubWidgets || {}
window.SBAdminRegisterDashboardSubWidget = function(groupId, definition) {
    const group = window.SBAdminDashboardGroups[groupId]
    if (group) {
        group.registerSubWidget(definition)
        return
    }
    window.SBAdminDashboardGroupPendingSubWidgets[groupId] = window.SBAdminDashboardGroupPendingSubWidgets[groupId] || []
    window.SBAdminDashboardGroupPendingSubWidgets[groupId].push(definition)
}

if (window.SBAdminMainLoaded) {
    initDashboardGroups()
} else {
    document.addEventListener('SBAdminMainLoaded', initDashboardGroups, {once: true})
}
document.dispatchEvent(new Event('SBAdminDashboardGroupLoaded'))
