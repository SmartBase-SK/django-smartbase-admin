import Choices from "choices.js"
import {createIcon} from "./utils"


export const choicesJSOptions = (choiceInput) => ({
    'allowHTML': true,
    'classNames': {
        'inputCloned': 'input choices__input choices__input--cloned'
    },
    removeItemButton: true,
    removeItems: true,
    placeholder: true,
    shouldSort: false,
    resetScrollPosition: false,
    callbackOnCreateTemplates: () => {
        return {
            item: (templateOptions, item, removeItemButton) => {
                const originalItem = Choices.defaults.templates.item.call(this, templateOptions, item, removeItemButton)
                if (removeItemButton) {
                    originalItem.children[0].innerHTML = ''
                    originalItem.children[0].appendChild(createIcon('Close-small', []))
                }
                return originalItem
            },
            choice: (templateOptions, choice, selectText) => {
                const originalItem = Choices.defaults.templates.choice.call(this, templateOptions, choice, selectText)
                if(!choiceInput.hasAttribute('multiple')) {
                    return originalItem
                }
                const input = document.createElement('input')
                input.id = `checkbox-${choice.elementId}`
                input.name = `checkbox-name-${choice.elementId}`
                input.classList.add('checkbox')
                input.type = 'checkbox'
                if (choice.selected) {
                    input.checked = true
                }

                const label = document.createElement('label')
                label.htmlFor = input.id
                label.innerHTML = choice.label
                originalItem.innerHTML = ''
                originalItem.appendChild(input)
                originalItem.appendChild(label)
                return originalItem
            }
        }
    },
})


const getChoiceValueForInput = (currentValue) => {
    let value = {
        'value': currentValue.value,
        'label': currentValue.label,
    }
    if(currentValue.customProperties?.create){
        value['create'] = true
    }
    return value
}

export const choicesJSListeners = {
    'selectItem': (item, inputEl) => {
        if (!item) return
        const choiceValue = [getChoiceValueForInput(item)]
        inputEl.value = JSON.stringify(choiceValue)
    },
    'addItem': (choicesJS, inputEl) => {
        const choiceValue = []
        let choicesJSValue = choicesJS.getValue()
        choicesJSValue = Array.isArray(choicesJSValue) ? choicesJSValue : [choicesJSValue]
        choicesJSValue.forEach(function (currentValue) {
            choiceValue.push(getChoiceValueForInput(currentValue))
        })
        inputEl.value = JSON.stringify(choiceValue)
    },
    'removeItem': (choicesJS, inputEl) => {
        const choiceValue = []
        let choicesJSValue = choicesJS.getValue()
        if (choicesJSValue !== undefined) {
            choicesJSValue = Array.isArray(choicesJSValue) ? choicesJSValue : [choicesJSValue]
            choicesJSValue.forEach(function (currentValue) {
                choiceValue.push(getChoiceValueForInput(currentValue))
            })
        }
        inputEl.value = JSON.stringify(choiceValue)
    },
}


export default class ChoicesJS {
    constructor() {
        const choiceElements = document.querySelectorAll('.js-choice')
        choiceElements.forEach((choiceInput) => {
            const inputElId = choiceInput.dataset.inputElId
            const inputEl = document.getElementById(inputElId)
            const choicesJS = new Choices(choiceInput, {
                renderSelectedChoices: 'always',
                ...choicesJSOptions(choiceInput)
            })
            choiceInput.addEventListener('addItem', () => {
                choicesJSListeners.addItem(choicesJS, inputEl)
                inputEl.dispatchEvent(new Event('change'))
            })
            choiceInput.addEventListener('removeItem', () => {
                choicesJSListeners.removeItem(choicesJS, inputEl)
                inputEl.dispatchEvent(new Event('change'))
            })
            inputEl.addEventListener('SBTableFilterFormLoad', () => {
                choicesJS.removeActiveItems(null)
                if (inputEl.value) {
                    const parsedValue = JSON.parse(inputEl.value)
                    choicesJS.setValue(parsedValue)
                }
            })
            choicesJS.containerOuter.element.classList.add('search-off')

            inputEl.addEventListener('clear', () => {
                inputEl.value = ''
                inputEl.dispatchEvent(new Event('change'))
                inputEl.dispatchEvent(new Event('clearSelectedItems'))
            })

            inputEl.addEventListener('clearSelectedItems', () => {
                choicesJS.removeActiveItems(null)
            })
        })
    }
}
