from django.apps import AppConfig


class CustomersConfig(AppConfig):
    name = "apps.customers"
    label = "customers"
    default_auto_field = "django.db.models.BigAutoField"
