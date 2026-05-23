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
    
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Transaction(models.Model):

    TRANSACTION_TYPES = (
        ('deposit',  'Deposit'),
        ('withdraw', 'Withdraw'),
        ('transfer', 'Transfer'),
        ('airtime',  'Airtime'),
        ('data',     'Data'),
    )

    STATUS_TYPES = (
        ('pending',    'Pending'),
        ('successful', 'Successful'),
        ('failed',     'Failed'),
    )

    user    = models.ForeignKey(User,    on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)

    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status           = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')

    reference = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        default=uuid.uuid4,   # ← added: guarantees a value even before save() runs
    )

    fee         = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    description = models.CharField(max_length=255, blank=True, null=True)
    created_at  = models.DateTimeField(default=timezone.now)

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
        ('MTN', 'MTN'),
        ('AIRTEL', 'AIRTEL'),
        ('GLO', 'GLO'),
        ('9MOBILE', '9MOBILE'),
    )

    STATUS_TYPES = (
        ('pending', 'Pending'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    network = models.CharField(max_length=20, choices=NETWORKS)

    phone_number = models.CharField(max_length=11)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=20, choices=STATUS_TYPES, default='pending')

    
    reference = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone_number} - {self.network}"


# models.py
from django.db import models

class Report(models.Model):
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message[:50]  # Show first 50 chars of the report in admin