from threading import local

_thread_locals = local()


class SBAdminThreadLocalService:
    THREAD_DATA_KEY = "SB_ADMIN_DATA"

    @classmethod
    def get_wrapper(cls):
        return getattr(_thread_locals, cls.THREAD_DATA_KEY, {})

    @classmethod
    def get_data(cls, key):
        data_wrapper = cls.get_wrapper()
        return data_wrapper.get(key)

    @classmethod
    def set_data(cls, key, data):
        data_wrapper = cls.get_wrapper()
        data_wrapper[key] = data

    @classmethod
    def clear_data(cls):
        if hasattr(_thread_locals, cls.THREAD_DATA_KEY):
            delattr(_thread_locals, cls.THREAD_DATA_KEY)
