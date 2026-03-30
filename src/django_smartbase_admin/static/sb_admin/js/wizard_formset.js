/**
 * Dynamické riadky ModelFormSet vo wizardi (ako Django admin inliny).
 * Klonuje markup z <template> a nahrádza __prefix__ indexom (TOTAL_FORMS).
 */
(function () {
    function replaceFormsetPrefix(root, index) {
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

    function initWizardFormset(container) {
        var prefix = container.getAttribute("data-prefix");
        if (!prefix) return;
        var maxForms = parseInt(container.getAttribute("data-max-forms") || "1000", 10);
        var totalInput = container.querySelector(
            'input[name="' + prefix + '-TOTAL_FORMS"]'
        );
        var formsWrap = container.querySelector(".wizard-formset-forms");
        var tpl = document.getElementById(prefix + "-empty-template");
        var addBtn = container.querySelector(".wizard-formset-add");
        if (!totalInput || !formsWrap || !tpl || !tpl.content || !addBtn) return;

        addBtn.addEventListener("click", function (e) {
            e.preventDefault();
            var total = parseInt(totalInput.value, 10);
            if (isNaN(total) || total >= maxForms) return;
            var row = tpl.content.firstElementChild.cloneNode(true);
            if (!row) return;
            replaceFormsetPrefix(row, total);
            row.querySelectorAll("script").forEach(function (s) {
                s.remove();
            });
            formsWrap.appendChild(row);
            totalInput.value = total + 1;
            document.body.dispatchEvent(
                new CustomEvent("wizard-formset-row-added", {
                    bubbles: true,
                    detail: { row: row, formsetPrefix: prefix },
                })
            );
        });
    }

    function run() {
        document
            .querySelectorAll(".wizard-formset-dynamic")
            .forEach(initWizardFormset);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }
})();
