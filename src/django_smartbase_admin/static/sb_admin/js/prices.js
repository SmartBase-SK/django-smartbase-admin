(function ($) {

    $(document).ready(function () {
    	addChangeListener('price_incl_tax', 'price_excluding_tax', false);
    	addChangeListener('price_excluding_tax', 'price_incl_tax', true);
    	$(document).on('change', "select[id$='tax_ratio']", function() {
    		var $parent = get_price_inline_block(this);
    		if ($parent.find("input[id$='" + 'price_incl_tax' + "']").val() !== '') {
				count_price($parent.find("input[id$='" + 'price_incl_tax' + "']"), $parent.find("input[id$='" + 'price_excluding_tax' + "']"), false);
			}
			else {
				count_price($parent.find("input[id$='" + 'price_excluding_tax' + "']"), $parent.find("input[id$='" + 'price_incl_tax' + "']"), true);
			}
        });
    });

    function addChangeListener(fieldName, changeFieldName, multiply){
		$(document).on('change', "input[id$='" + fieldName + "']", function() {
			var $parent = get_price_inline_block(this);
			count_price($(this), $parent.find("input[id$='" + changeFieldName + "']"), multiply);
    	});
    }

    var count_price = function (from, to, multiply) {
		var $parent = get_price_inline_block(from);
		var $tax_ratio = $parent.find("input[id$='tax_ratio']")
		var tax_ratio_value = $tax_ratio.val();
		if(tax_ratio_value === "") {
			$tax_ratio.closest(".related-widget-wrapper").addClass("errors");
			return;
		}else{
			$tax_ratio.closest(".related-widget-wrapper").removeClass("errors");
		}
        tax_ratio_value = JSON.parse(tax_ratio_value)[0].label;
        if (multiply) {
        	$(to).val(($(from).val() * ((tax_ratio_value / 100) + 1)).toFixed(5));
        }
        else {
        	$(to).val(($(from).val() / ((tax_ratio_value / 100) + 1)).toFixed(5));
        }
    }

    function get_price_inline_block(innerElement){
    	return $(innerElement).closest("tbody[id*='pricing-price-content_type-object_id'], tbody[id*='pricing-oldprice-content_type-object_id']");
	}

})(django.jQuery);
