/**
 * Dynamic formset rows for SBAdmin (used in wizards and other views).
 * Clones markup from <template> and replaces __prefix__ with the row index.
 */
(function () {
    var FORMSET_SELECTOR = ".sbadmin-formset-dynamic";
    var ROW_SELECTOR = ".sbadmin-formset-row";
    var DELETE_ROW_SELECTOR = "[data-sbadmin-formset-delete-row]";

    function replacePrefix(root, index) {
        var idx = String(index);
        var nodes = [root];
        var q = root.querySelectorAll("*");
        for (var i = 0; i < q.length; i++) nodes.push(q[i]);
        for (var n = 0; n < nodes.length; n++) {
            var el = nodes[n];
            if (!el.attributes) continue;
            for (var a = 0; a < el.attributes.length; a++) {
                var attr = el.attributes[a];
                if (attr.value.indexOf("__prefix__") !== -1) {
                    el.setAttribute(attr.name, attr.value.replace(/__prefix__/g, idx));
                }
            }
        }
    }

    function initFormset(container) {
        var prefix = container.getAttribute("data-prefix");
        if (!prefix) return;
        var maxForms = parseInt(container.getAttribute("data-max-forms") || "1000", 10);
        var totalInput = container.querySelector(
            'input[name="' + prefix + '-TOTAL_FORMS"]'
        );
        var formsWrap = container.querySelector(".sbadmin-formset-forms");
        var tpl = document.getElementById(prefix + "-empty-template");
        var addBtn = container.querySelector(".sbadmin-formset-add");
        if (!totalInput || !formsWrap || !tpl || !tpl.content || !addBtn) return;

        addBtn.addEventListener("click", function (e) {
            e.preventDefault();
            var total = parseInt(totalInput.value, 10);
            if (isNaN(total) || total >= maxForms) return;
            var row = tpl.content.firstElementChild.cloneNode(true);
            if (!row) return;
            replacePrefix(row, total);
            row.id = prefix + "-" + total;
            row.removeAttribute("data-sbadmin-formset-initial-row");
            row.style.order = total;
            row.querySelectorAll("script:not([type='application/json'])").forEach(function (s) {
                s.remove();
            });
            // Keep dynamically added rows after all rows rendered by the server.
            formsWrap.appendChild(row);
            totalInput.value = total + 1;
            syncDeleteButtons(container);
            row.dispatchEvent(
                new CustomEvent("formset:added", {
                    bubbles: true,
                    detail: { formsetName: prefix },
                })
            );
        });
    }

    function getVisibleRows(formsWrap) {
        if (!formsWrap) return [];
        return Array.prototype.slice.call(
            formsWrap.querySelectorAll(ROW_SELECTOR + ":not(.hidden)")
        );
    }

    function syncDeleteButtons(formset) {
        if (!formset) return;
        var formsWrap = formset.querySelector(".sbadmin-formset-forms");
        var protectedRows = parseInt(
            formset.getAttribute("data-delete-protected-rows") || "0",
            10
        );
        if (isNaN(protectedRows)) protectedRows = 0;
        var visibleRows = getVisibleRows(formsWrap);
        var protectedVisibleInitialRows = visibleRows
            .filter(function (row) {
                return row.hasAttribute("data-sbadmin-formset-initial-row");
            })
            .slice(0, protectedRows);
        visibleRows.forEach(function (row) {
            var isProtected = protectedVisibleInitialRows.indexOf(row) !== -1;
            row.querySelectorAll(DELETE_ROW_SELECTOR).forEach(function (button) {
                button.classList.toggle("hidden", isProtected);
                button.hidden = isProtected;
            });
        });
    }

    function deleteFormsetRow(button) {
        var row = button.closest(ROW_SELECTOR);
        if (!row) return;
        var formset = row.closest(FORMSET_SELECTOR);
        var formsWrap = row.closest(".sbadmin-formset-forms");
        var minForms = parseInt(
            formset ? formset.getAttribute("data-min-forms") || "0" : "0",
            10
        );
        if (isNaN(minForms)) minForms = 0;
        var visibleRows = getVisibleRows(formsWrap);
        if (visibleRows.length <= minForms) return;

        var deleteInput = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
        if (deleteInput) {
            deleteInput.checked = true;
        }
        row.classList.add("hidden");
        syncDeleteButtons(formset);
    }

    function handleClick(event) {
        var deleteButton = event.target.closest(DELETE_ROW_SELECTOR);
        if (!deleteButton) return;
        event.preventDefault();
        deleteFormsetRow(deleteButton);
    }

    function run() {
        document
            .querySelectorAll(FORMSET_SELECTOR)
            .forEach(function (formset) {
                initFormset(formset);
                syncDeleteButtons(formset);
            });
    }

    document.addEventListener("click", handleClick);

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }
})();
