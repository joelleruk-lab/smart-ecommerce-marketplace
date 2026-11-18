from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'store'
    verbose_name = 'Rukomeza Marketplace'

    def ready(self):
        from . import signals  # noqa: F401  (registers post_save handlers)
