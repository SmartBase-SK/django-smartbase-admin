import Choices from "choices.js"
import {choicesJSOptions} from "./choices"
import {createIcon, getResultLabel, syncDropdownMenuWidth} from "./utils"

// Shares the autocomplete UI shell (dropdown button + Choices.js wrapped
// <select>) but uses a static list of <option> tags rendered server-side —
// no API fetch, no pagination, no add-new, no hidden JSON input. The <select>
// submits natively, so Django's default MultipleChoiceField/ChoiceField
// value_from_datadict handles the POST with no custom widget parsing.
export default class StaticAutocomplete {
    constructor() {
        this.handleDynamicallyAdded(document)
        document.addEventListener('formset:added', (event) => {
            this.handleDynamicallyAdded(event.target)
        })
    }

    handleDynamicallyAdded(root) {
        root.querySelectorAll('.js-static-autocomplete').forEach((choiceInput) => {
            this.init(choiceInput)
        })
    }

    init(choiceInput) {
        if (choiceInput.closest('.choices')) return
        const wrapperEl = document.getElementById(`${choiceInput.id}-wrapper`)
        if (!wrapperEl) return
        const wrapperElButton = wrapperEl.querySelector('button[data-bs-toggle="dropdown"]')
        const deleteButton = wrapperEl.querySelector('.js-clear-autocomplete')
        const labelEl = document.getElementById(`${choiceInput.id}-value`)
        const emptyLabel = labelEl ? labelEl.textContent.trim() : ''

        const choicesJS = new Choices(choiceInput, {
            ...choicesJSOptions(choiceInput),
            placeholderValue: window.sb_admin_translation_strings?.["search"] || 'Search',
            searchPlaceholderValue: window.sb_admin_translation_strings?.["search"] || 'Search',
            noResultsText: window.sb_admin_translation_strings?.["no_results"] || 'No results found',
            noChoicesText: window.sb_admin_translation_strings?.["no_choices"] || 'No choices to choose from',
            searchEnabled: true,
            searchChoices: true,
            searchResultLimit: 999,
            // Default renderSelectedChoices ('auto'): selected items leave the
            // dropdown and show as removable pills above it — matches dynamic
            // multi-select autocomplete behavior.
            callbackOnInit: () => {
                const label = document.createElement('label')
                label.appendChild(createIcon('Find', []))
                choiceInput.parentElement.appendChild(label)
            },
        })

        const updateLabel = () => {
            if (!labelEl) return
            const value = choicesJS.getValue()
            const items = Array.isArray(value) ? value : (value ? [value] : [])
            labelEl.innerHTML = items.length === 0 ? emptyLabel : getResultLabel(items)
        }
        choiceInput.addEventListener('addItem', updateLabel)
        choiceInput.addEventListener('removeItem', updateLabel)
        updateLabel()

        if (!choiceInput.hasAttribute('multiple')) {
            // Single-select: close the dropdown after picking.
            choiceInput.addEventListener('change', () => {
                if (wrapperElButton) wrapperElButton.click()
            })
        }

        if (wrapperElButton) {
            wrapperElButton.addEventListener('shown.bs.dropdown', () => {
                choicesJS.input.element.focus()
            })
            syncDropdownMenuWidth(wrapperEl, wrapperElButton)
        }

        if (deleteButton) {
            deleteButton.addEventListener('click', () => {
                choicesJS.removeActiveItems(null)
                updateLabel()
            })
        }

        // Render with the search input visible immediately — the whole point
        // of the static widget is its client-side search.
        choicesJS.containerOuter.element.classList.add('search-on')
        choicesJS.input.element.focus()
    }
}
