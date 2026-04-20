import Choices from "choices.js"

import {choicesJSOptions} from "./choices"


const TEXT_TAGS_SELECTOR = "input.js-sbadmin-text-tags"
const TEXT_TAGS_OUTER_CLASS = "choices--sbadmin-text-tags"

export default class TextTags {
    constructor() {
        document.addEventListener("formset:added", (event) => {
            this.handleDynamicallyAddedTextTags(event.target)
        })
        this.handleDynamicallyAddedTextTags(document)
    }

    handleDynamicallyAddedTextTags(root) {
        const el = root || document
        el.querySelectorAll(TEXT_TAGS_SELECTOR).forEach((inputEl) => {
            this.initTextTags(inputEl)
        })
    }

    getTagsOptions(inputEl) {
        const base = choicesJSOptions(inputEl)
        const delimiter = inputEl.dataset.choicesDelimiter || ","
        const placeholder = inputEl.getAttribute("placeholder") || ""
        const hasPlaceholder = Boolean(placeholder)
        return {
            ...base,
            allowHTML: false,
            delimiter,
            editItems: true,
            duplicateItemsAllowed: false,
            searchEnabled: false,
            addItems: true,
            paste: true,
            shouldSort: false,
            placeholder: hasPlaceholder,
            placeholderValue: hasPlaceholder ? placeholder : undefined,
        }
    }

    initTextTags(inputEl) {
        if (inputEl.closest(".choices")) {
            return
        }
        if (inputEl.closest(".empty-form")) {
            return
        }
        const instance = new Choices(inputEl, this.getTagsOptions(inputEl))
        instance.containerOuter.element.classList.add(TEXT_TAGS_OUTER_CLASS)
    }
}
