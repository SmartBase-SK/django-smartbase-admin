from django.db import models


class SBAdminListViewConfigurationQueryset(models.QuerySet):
    def by_id(self, config_id):
        return self.filter(id=config_id)

    def by_user_id(self, user_id):
        return self.filter(user_id=user_id)

    def by_view_action_modifier(self, view, action=None, modifier=None):
        return self.filter(view=view, action=action, modifier=modifier)

    def by_name(self, name):
        return self.filter(name=name)
