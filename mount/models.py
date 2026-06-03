from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid
import random


class Detail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.user.username if self.user else "No User"


class Account(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    account_number = models.CharField(max_length=10, unique=True, blank=True)
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    virtual_account_number = models.CharField(max_length=20, blank=True, null=True)

    def generate_account_number(self):
        while True:
            number = str(random.randint(1000000000, 9999999999))
            if not Account.objects.filter(account_number=number).exists():
                return number

    def save(self, *args, **kwargs):
        if not self.account_number:
            self.account_number = self.generate_account_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.user.username if self.user else "No User"


class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('deposit',  'Deposit'),
        ('withdraw', 'Withdraw'),
        ('transfer', 'Transfer'),
        ('airtime',  'Airtime'),
        ('data',     'Data'),
        ('smm',      'SMM Service'),
    )
    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('successful', 'Successful'),
        ('failed',     'Failed'),
    )

    user             = models.ForeignKey(User, on_delete=models.CASCADE)
    account          = models.ForeignKey(Account, on_delete=models.CASCADE)
    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status           = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')
    reference        = models.CharField(
        max_length=100, unique=True, blank=True, null=True, default=uuid.uuid4,
    )
    fee              = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    description      = models.CharField(max_length=255, blank=True, null=True)
    created_at       = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.transaction_type} - {self.amount}"


class DataPurchase(models.Model):
    NETWORKS = (
        ('MTN',    'MTN'),
        ('AIRTEL', 'AIRTEL'),
        ('GLO',    'GLO'),
        ('9MOBILE','9MOBILE'),
    )
    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('successful', 'Successful'),
        ('failed',     'Failed'),
    )

    user         = models.ForeignKey(User, on_delete=models.CASCADE)
    network      = models.CharField(max_length=20, choices=NETWORKS)
    phone_number = models.CharField(max_length=11)
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    status       = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')
    reference    = models.CharField(max_length=100, unique=True, blank=True, null=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone_number} - {self.network}"


class SMMOrder(models.Model):
    PLATFORMS = (
        ('instagram', 'Instagram'),
        ('tiktok',    'TikTok'),
        ('youtube',   'YouTube'),
        ('facebook',  'Facebook'),
    )
    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('processing', 'Processing'),
        ('completed',  'Completed'),
        ('partial',    'Partial'),
        ('cancelled',  'Cancelled'),
        ('failed',     'Failed'),
    )

    user         = models.ForeignKey(User, on_delete=models.CASCADE)
    platform     = models.CharField(max_length=20, choices=PLATFORMS)
    service_name = models.CharField(max_length=200)
    service_id   = models.CharField(max_length=20)
    link         = models.URLField(max_length=500)
    quantity     = models.PositiveIntegerField()
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    jap_order_id = models.CharField(max_length=100, blank=True, null=True)
    status       = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.service_name} x{self.quantity}"


class Report(models.Model):
    message    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message[:50]
    



class ForeignNumber(models.Model):

    STATUS_CHOICES = (
        ("PENDING", "PENDING"),
        ("RECEIVED", "RECEIVED"),
        ("CANCELLED", "CANCELLED"),
        ("FINISHED", "FINISHED"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    order_id = models.CharField(
        max_length=100,
        unique=True
    )

    country = models.CharField(
        max_length=100
    )

    service = models.CharField(
        max_length=100
    )

    phone_number = models.CharField(
        max_length=100
    )

    price = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    sms_code = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )
    provider = models.CharField(max_length=20, default="5sim")  # "5sim" or "steadysim"
    def __str__(self):
        return self.phone_number

# Add these two models to your existing models.py
# Place them at the bottom, after the ForeignNumber model
# Add these two models to your existing models.py
# Place them at the bottom, after the ForeignNumber model

class ElectricityPurchase(models.Model):
    # Column names match your existing database table exactly
    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('successful', 'Successful'),
        ('failed',     'Failed'),
    )
    user              = models.ForeignKey(User, on_delete=models.CASCADE)
    electric_provider = models.CharField(max_length=100)     # company name
    meter_type        = models.CharField(max_length=20)      # "Prepaid" or "Postpaid"
    meter_number      = models.CharField(max_length=50)      # meter number
    amount            = models.DecimalField(max_digits=12, decimal_places=2)
    token             = models.CharField(max_length=100, blank=True, null=True)
    reference         = models.CharField(max_length=100, unique=True, blank=True, null=True)
    status            = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.electric_provider} - ₦{self.amount}"


class CableTVPurchase(models.Model):
    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('successful', 'Successful'),
        ('failed',     'Failed'),
    )
    user          = models.ForeignKey(User, on_delete=models.CASCADE)
    provider      = models.CharField(max_length=20)          # e.g. "dstv"
    provider_name = models.CharField(max_length=50)          # e.g. "DStv"
    package_code  = models.CharField(max_length=50)          # e.g. "dstv-padi"
    package_name  = models.CharField(max_length=100)         # e.g. "DStv Padi"
    smartcard_no  = models.CharField(max_length=50)
    phone         = models.CharField(max_length=15)
    amount        = models.DecimalField(max_digits=12, decimal_places=2)
    order_id      = models.CharField(max_length=100, blank=True, null=True)
    reference     = models.CharField(max_length=100, unique=True, blank=True, null=True)
    status        = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.provider_name} {self.package_name}"


