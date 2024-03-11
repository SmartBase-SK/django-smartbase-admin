from inspect import getfullargspec

from django.template.library import InclusionNode, parse_bits


class InclusionSBAdminNode(InclusionNode):
    """
    Template tag that allows its template to be overridden per model, per app,
    or globally.
    """

    def __init__(
        self, parser, token, func, template_name, takes_context=True, template_path=None
    ):
        self.template_name = template_name
        params, varargs, varkw, defaults, kwonly, kwonly_defaults, _ = getfullargspec(
            func
        )
        bits = token.split_contents()
        args, kwargs = parse_bits(
            parser,
            bits[1:],
            params,
            varargs,
            varkw,
            defaults,
            kwonly,
            kwonly_defaults,
            takes_context,
            bits[0],
        )
        super().__init__(func, takes_context, args, kwargs, filename=None)

    def render(self, context):
        opts = context["opts"]
        app_label = opts.app_label.lower()
        object_name = opts.object_name.lower()
        # Load template for this render call. (Setting self.filename isn't
        # thread-safe.)

        context.render_context[self] = context.template.engine.select_template(
            [
                "sb_admin/%s/%s/%s" % (app_label, object_name, self.template_name),
                "sb_admin/%s/%s" % (app_label, self.template_name),
                "sb_admin/%s" % self.template_name,
            ]
        )
        return super().render(context)
