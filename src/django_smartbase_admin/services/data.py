class SBAdminDataService(object):
    @classmethod
    def get_list_data(cls, model, columns):
        return list(model.objects.filter().values(*columns))
