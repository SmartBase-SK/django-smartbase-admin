import Choices from "choices.js"

import { choicesJSOptions } from "./choices"


const TEXT_TAGS_SELECTOR = "input.js-sbadmin-text-tags"
const TEXT_TAGS_OUTER_CLASS = "choices--sbadmin-text-tags"
const TEXT_TAGS_READONLY_CLASS = "choices--readonly"

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

    isReadonly(inputEl) {
        return inputEl.readOnly || inputEl.hasAttribute("readonly")
    }

    getTagsOptions(inputEl) {
        const base = choicesJSOptions(inputEl)
        const delimiter = inputEl.dataset.choicesDelimiter || ","
        const placeholder = inputEl.getAttribute("placeholder") || ""
        const hasPlaceholder = Boolean(placeholder)
        const options = {
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
        if (this.isReadonly(inputEl)) {
            return {
                ...options,
                editItems: false,
                paste: false,
                removeItemButton: false,
                placeholder: false,
                placeholderValue: undefined,
            }
        }
        return options
    }

    getPendingTags(instance, delimiter) {
        return instance.input.element.value
            .split(delimiter)
            .map((value) => value.trim())
            .filter(Boolean)
    }

    addPendingTags(instance, delimiter) {
        const pendingTags = this.getPendingTags(instance, delimiter)
        if (!pendingTags.length) {
            return
        }
        instance.setValue(pendingTags)
        instance.clearInput()
    }

    addPendingTagsOnBlurOrSubmit(inputEl, instance) {
        if (this.isReadonly(inputEl)) {
            return
        }
        const delimiter = inputEl.dataset.choicesDelimiter || ","
        instance.input.element.addEventListener("blur", () => {
            this.addPendingTags(instance, delimiter)
        })
        inputEl.form?.addEventListener("submit", () => {
            this.addPendingTags(instance, delimiter)
        })
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
        if (this.isReadonly(inputEl)) {
            instance.containerOuter.element.classList.add(TEXT_TAGS_READONLY_CLASS)
        }
        this.addPendingTagsOnBlurOrSubmit(inputEl, instance)
    }
}
