import { SBAdminTableModule } from "./base_module"

export class DashboardParentFilterModule extends SBAdminTableModule {
    getParentGroup() {
        return window.SBAdminDashboardGroups?.[this.table.parentWidgetId]
    }

    formValues() {
        const group = this.getParentGroup()
        return group ? group.formValues() : {}
    }

    getUrlParams() {
        if (!this.table.parentWidgetId) {
            return {}
        }
        const values = this.formValues()
        if (Object.keys(values).length === 0) {
            return {}
        }
        return {
            [this.table.constants.PARENT_FILTER_DATA_NAME]: values,
        }
    }

    afterInit() {
        if (!this.table.parentWidgetId) {
            return
        }
        window.SBAdminRegisterDashboardSubWidget(this.table.parentWidgetId, {
            widgetId: this.table.viewId,
            skipInitialData: true,
            onData: () => {
                this.table.tabulator.setData()
            },
        })
    }
}
