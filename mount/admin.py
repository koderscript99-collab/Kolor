from django.contrib import admin

# Register your models here.
from .models import DataPurchase, Transaction,Account,Detail,Report,ForeignNumber,ElectricityPurchase,CableTVPurchase


admin.site.register(DataPurchase)
admin.site.register(Account)
admin.site.register(Transaction)
admin.site.register(Detail)
admin.site.register(Report)
admin.site.register(ForeignNumber)
admin.site.register(ElectricityPurchase)
admin.site.register(CableTVPurchase)

class ReportAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    search_fields = ("user__username", "message", "admin_reply")