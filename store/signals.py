from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile, User


@receiver(post_save, sender=User)
def create_customer_profile(sender, instance, created, **kwargs):
    """Every customer automatically gets the 1:1 profile row.

    Seller/admin accounts get their role-specific tables through registration or
    administrator actions, so they are intentionally skipped here.
    """
    if created and instance.role == User.ROLE_CUSTOMER:
        CustomerProfile.objects.get_or_create(user=instance)
