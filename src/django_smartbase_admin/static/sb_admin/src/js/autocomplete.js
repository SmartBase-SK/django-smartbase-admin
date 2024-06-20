import Choices from "choices.js"
import {createIcon, filterInputValueChangedUtil} from "./utils"
import {choicesJSListeners, choicesJSOptions} from "./choices"
import debounce from "lodash/debounce"

export default class Autocomplete {
    constructor() {
        document.addEventListener('formset:added', (event) => {
            const totalFormsCount = document.querySelector(`#id_${event.detail.formsetName}-TOTAL_FORMS`).value - 1
            const formsetElements = document.querySelectorAll(`#${event.target.id} *`)
            formsetElements.forEach((formsetElement) => {
                const id_value = formsetElement.getAttribute('id')
                if (id_value) {
                    formsetElement.setAttribute('id', id_value.replace('__prefix__', totalFormsCount))
                }
            })
            const choiceElementsInline = document.querySelectorAll(`#${event.target.id} [data-autocomplete-data-id]`)
            choiceElementsInline.forEach((choiceInput) => {
                choiceInput.setAttribute('data-autocomplete-data-id', choiceInput.getAttribute('data-autocomplete-data-id').replace('__prefix__', totalFormsCount))
                this.initAutocomplete(choiceInput, totalFormsCount)
            })
            this.handleDynamiclyAddedAutocomplete(event.target)
        })
        document.body.addEventListener('SBModalShown', () => {
            this.handleDynamiclyAddedAutocomplete(document.getElementById('sb-admin-modal'))
        })
        this.handleDynamiclyAddedAutocomplete(document)
    }

    handleDynamiclyAddedAutocomplete(el) {
        const choiceElements = el.querySelectorAll('.js-autocomplete')
        choiceElements.forEach((choiceInput) => {
            this.initAutocomplete(choiceInput)
        })
        el.querySelectorAll('.js-autocomplete-detail').forEach(item => {
            filterInputValueChangedUtil(item)
            item.addEventListener('SBAutocompleteChange', (e) => {
                filterInputValueChangedUtil(e.target)
            })
        })
    }

    initAutocomplete(choiceInput, totalFormsCount = null) {
        const dataEl = document.getElementById(choiceInput.dataset.autocompleteDataId)
        const autocompleteData = JSON.parse(dataEl.textContent)
        let inputElId = autocompleteData.input_id
        if (totalFormsCount !== null) {
            inputElId = inputElId.replace('__prefix__', totalFormsCount)
        }
        const inputEl = document.getElementById(inputElId)
        if (!inputEl) {
            return
        }
        const isInlineEmptyForm = inputEl.closest(".empty-form")
        if (isInlineEmptyForm) {
            return
        }
        const wrapperEl = document.querySelector(`#${inputElId}-wrapper`)
        const wrapperElButton = document.querySelector(`#${inputElId}-wrapper > button`)
        const addNewButton = wrapperEl.querySelector(`.js-add-new-button`)
        const deleteButton = wrapperEl.querySelector(`.js-clear-autocomplete`)
        const options = JSON.parse(choiceInput.dataset.autocompleteOptions || "{}")
        const choicesJS = new Choices(choiceInput, {
            ...choicesJSOptions(choiceInput),
            placeholderValue: 'Search',
            searchChoices: false,
            searchPlaceholderValue: 'Search',
            searchResultLimit: 999,

            callbackOnInit: () => {
                const label = document.createElement('label')
                label.appendChild(createIcon('Find', []))
                choiceInput.parentElement.appendChild(label)
            },
            ...options
        })
        choicesJS.SBcurrentSearchTerm = ''
        choicesJS.SBcurrentPage = 1
        choicesJS.SBhasNextPage = true
        choicesJS.SBinitialised = false
        choicesJS.SBaddNewButton = addNewButton
        choicesJS.SBwrapperElButton = wrapperElButton

        choicesJS.input.element.addEventListener('input', debounce((e) => {
            choicesJS.SBcurrentSearchTerm = e.target.value
            // reset pagination
            choicesJS.SBcurrentPage = 1
            choicesJS.SBhasNextPage = true
            this.search(choicesJS.SBcurrentSearchTerm, choicesJS, inputEl, autocompleteData, choicesJS.SBcurrentPage)
        }, 200))
        choiceInput.addEventListener('addItem', () => {
            choicesJSListeners.addItem(choicesJS, inputEl)
        })
        choiceInput.addEventListener('removeItem', () => {
            choicesJSListeners.removeItem(choicesJS, inputEl)
        })
        choiceInput.addEventListener('change', (e) => {
            if(!e.target.hasAttribute('multiple')) {
                choicesJS.SBwrapperElButton.click()
            }
            inputEl.dispatchEvent(new CustomEvent('SBAutocompleteChange'))
        })
        const initLoad = () => {
            choicesJS.SBhasNextPage = true
            choicesJS.SBcurrentPage = 1
            choicesJS.clearInput()
            this.search('', choicesJS, inputEl, autocompleteData, choicesJS.SBcurrentPage, !choicesJS.SBinitialised)
        }

        if(wrapperElButton){
            // filter in dropdown
            wrapperElButton.addEventListener('show.bs.dropdown', initLoad)
        } else {
            choicesJS.input.element.addEventListener('focus', initLoad)
        }
        inputEl.addEventListener('clear', (e) => {
            choicesJS.clearStore()
            if (e.detail && e.detail['refresh']) {
                choicesJS.SBhasNextPage = true
                choicesJS.SBcurrentPage = 1
                this.search('', choicesJS, inputEl, autocompleteData, choicesJS.SBcurrentPage, false)
            }
        })
        addNewButton?.addEventListener('click', (event) => {
            choicesJS.clearStore()
            choicesJS.setValue([event.currentTarget.dataset.value])
            choicesJS.SBwrapperElButton.click()
            filterInputValueChangedUtil(inputEl)
        })
        inputEl.addEventListener('clearSelectedItems', () => {
            choicesJS.removeActiveItems(null)
            filterInputValueChangedUtil(inputEl)
        })
        inputEl.addEventListener('SBTableFilterFormLoad', () => {
            choicesJS.clearStore()
            this.loadChoicesFromValue(inputEl, choicesJS)
        })
        const choicesListElem = choicesJS.choiceList.element
        let lastScrollTop = 0
        choicesListElem.addEventListener('scroll', () => {
            lastScrollTop = choicesListElem.scrollTop <= 0 ? 0 : choicesListElem.scrollTop
            if (choicesListElem.scrollTop < lastScrollTop) {
                return
            }
            if (choicesListElem.scrollTop + choicesListElem.offsetHeight >= choicesListElem.scrollHeight) {
                // advance pagination
                if (choicesJS.SBhasNextPage) {
                    this.search(choicesJS.SBcurrentSearchTerm, choicesJS, inputEl, autocompleteData, choicesJS.SBcurrentPage + 1)
                }
            }
        })
        if (deleteButton) {
            deleteButton.addEventListener('click', () => {
                inputEl.value = ''
                inputEl.dispatchEvent(new Event('change'))
                inputEl.dispatchEvent(new Event('clearSelectedItems'))
            })
        }

        this.loadChoicesFromValue(inputEl, choicesJS)
    }

    loadChoicesFromValue(inputEl, choicesJS) {
        document.querySelectorAll('.filter-dropdown-button.show').forEach((el) => {
            el.classList.remove('show')
        })
        document.querySelectorAll('.dropdown-menu.show').forEach((el) => {
            el.classList.remove('show')
        })
        choicesJS.SBinitialiseValue = null
        choicesJS.SBinitialised = false
        if (inputEl.value) {
            const parsedValue = JSON.parse(inputEl.value)
            choicesJS.SBinitialiseValue = parsedValue
        }
    }

    initialisation(choicesJS, searchOn) {
        if (searchOn) {
            choicesJS.containerOuter.element.classList.add('search-on')
            choicesJS.containerOuter.element.classList.remove('search-off')
        } else {
            choicesJS.containerOuter.element.classList.remove('search-on')
            choicesJS.containerOuter.element.classList.add('search-off')
        }
    }

    toggleAddNew(choicesJS, label, show=false) {
        if(!choicesJS.SBaddNewButton) {
            return
        }
        const buttonText = choicesJS.SBaddNewButton.querySelector('.js-add-item-label')
        buttonText.innerText = label
        choicesJS.SBaddNewButton.dataset.value = label
        if(show) {
            choicesJS.SBaddNewButton.parentElement.classList.remove('hidden')
        } else {
            choicesJS.SBaddNewButton.parentElement.classList.add('hidden')
        }
    }

    search(searchTerm, choicesJS, inputEl, autocompleteData, requestedPage, initialisation = false) {
        const autocompleteRequestData = new FormData()
        const autocompleteForwardData = {}
        if (autocompleteData.forward) {
            autocompleteData.forward.forEach(fieldToForward => {
                // replace current field id for forward field id keeping the view_id or inline_id prefixes intact
                const fieldToForwardInputId = inputEl.id.replace(new RegExp(autocompleteData.field_name + '$'), fieldToForward)
                autocompleteForwardData[fieldToForward] = document.getElementById(fieldToForwardInputId).value
            })
        }
        autocompleteRequestData.set(autocompleteData.constants.autocomplete_forward, JSON.stringify(autocompleteForwardData))
        autocompleteRequestData.set(autocompleteData.constants.autocomplete_requested_page, requestedPage)
        autocompleteRequestData.set(autocompleteData.constants.autocomplete_term, searchTerm)
        fetch(autocompleteData.autocomplete_url, {
            method: 'POST',
            headers: {
                "X-CSRFToken": window.csrf_token,
            },
            body: autocompleteRequestData
        }).then(response => response.json())
            .then(res => {
                let currentChoices = []
                let exactSearchTermMatched = false

                if (requestedPage !== 1) {
                    currentChoices = choicesJS._store.choices
                }
                const responseChoices = res.data
                const choicesJSChoices = [...currentChoices, ...responseChoices]

                let choicesValue = choicesJS.getValue()
                if (initialisation && choicesJS.SBinitialiseValue) {
                    choicesValue = choicesJS.SBinitialiseValue
                }
                if (choicesValue) {
                    const choiceValueArray = Array.isArray(choicesValue) ? choicesValue : [choicesValue]
                    choicesJSChoices.forEach((choice) => {
                        const index = choiceValueArray.findIndex(val => val.value === choice.value)
                        if (index > -1) {
                            choice.selected = true
                            choiceValueArray.splice(index, 1)
                        }
                    })
                    if (choiceValueArray.length > 0) {
                        choiceValueArray.forEach(value => {
                            choicesJSChoices.push({
                                value: value.value,
                                label: value.label,
                                selected: true
                            })
                        })
                    }
                    choicesJS.clearStore()
                }

                choicesJSChoices.forEach((choice) => {
                    if(choice.label === searchTerm) {
                        exactSearchTermMatched = true
                    }
                })

                this.toggleAddNew(choicesJS, searchTerm, searchTerm && !exactSearchTermMatched)
                choicesJS.setChoices(choicesJSChoices, 'value', 'label', true)

                if (initialisation) {
                    if (choicesJSChoices.length < window.sb_admin_const.AUTOCOMPLETE_PAGE_SIZE && !choicesJS.SBaddNewButton) {
                        this.initialisation(choicesJS, false)
                    } else {
                        this.initialisation(choicesJS, true)
                    }
                    choicesJS.SBinitialised = true
                }
                if (responseChoices.length === 0) {
                    choicesJS.SBhasNextPage = false
                }
                choicesJS.SBcurrentPage = requestedPage
            })
    }
}
