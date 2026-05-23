from django.contrib import admin

# Register your models here.
from .models import DataPurchase, Transaction,Account,Detail,Report


admin.site.register(DataPurchase)
admin.site.register(Account)
admin.site.register(Transaction)
admin.site.register(Detail)
admin.site.register(Report)
