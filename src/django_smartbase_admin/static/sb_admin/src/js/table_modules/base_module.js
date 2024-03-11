export class SBAdminTableModule {

    constructor(table) {
        this.table = table
    }

    beforeDefaultColumns() {
        return []
    }

    requiresHeader() {
        return false
    }

    afterUrlStateUpdate() {
    }

    loadFromUrl() {
    }

    loadFromUrlAfterInit() {
    }

    afterInit() {
    }

    getUrlParams() {
    }

    modifyTabulatorOptions(tabulatorOptions) {
        return tabulatorOptions
    }

    getUrlParamsForSave() {
        return this.getUrlParams()
    }
}
