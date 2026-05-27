from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import transaction as db_transaction

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from decimal import Decimal, InvalidOperation
import json
import uuid
import requests
import logging

from decouple import config

from .models import Account, Transaction, Detail, DataPurchase, Report, SMMOrder
from .serializers import DetailSerializer

logger = logging.getLogger(__name__)


# =========================
# HELPERS
# =========================

def get_or_create_account(user):
    account, _ = Account.objects.get_or_create(user=user)
    return account


def flw_headers():
    return {"Authorization": f"Bearer {settings.FLW_SECRET_KEY}"}


def credit_account(transaction_obj):
    with db_transaction.atomic():
        transaction_obj = Transaction.objects.select_for_update().get(pk=transaction_obj.pk)
        if transaction_obj.status == "successful":
            return False
        account = Account.objects.select_for_update().get(pk=transaction_obj.account_id)
        account.balance += transaction_obj.amount
        account.save()
        transaction_obj.status = "successful"
        transaction_obj.save()
    return True


# =========================
# AUTH (WEB)
# =========================

def signup(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email    = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect("signup")

        if User.objects.filter(username=username).exists():
            messages.error(request, "That username is already taken.")
            return redirect("signup")

        User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, "Account created! Please log in.")
        return redirect("login")

    return render(request, "signup.html")


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user     = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        messages.error(request, "Invalid username or password.")
        return redirect("login")
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# =========================
# CLUBKONNECT DATA PLANS
# =========================

NETWORK_CODES = {
    "MTN":     "01",
    "GLO":     "02",
    "AIRTEL":  "04",
    "9MOBILE": "03",
}

DATA_PLANS = {
    "MTN": [
        {"id": "500.0",    "label": "500MB - 7 days (SME)",           "amount": 305},
        {"id": "1000.0",   "label": "1GB - 7 days (SME)",             "amount": 567},
        {"id": "2000.0",   "label": "2GB - 7 days (SME)",             "amount": 1134},
        {"id": "3000.0",   "label": "3GB - 7 days (SME)",             "amount": 1659},
        {"id": "5000.0",   "label": "5GB - 7 days (SME)",             "amount": 2540},
        {"id": "100.01",   "label": "110MB - 1 day (Awoof)",          "amount": 100},
        {"id": "200.01",   "label": "230MB - 1 day (Awoof)",          "amount": 200},
        {"id": "350.01",   "label": "500MB - 1 day (Awoof)",          "amount": 350},
        {"id": "500.01",   "label": "1GB Daily + 1.5mins (Awoof)",    "amount": 500},
        {"id": "750.01",   "label": "2.5GB - 1 day (Awoof)",          "amount": 750},
        {"id": "900.01",   "label": "2.5GB - 2 days (Awoof)",         "amount": 900},
        {"id": "1000.01",  "label": "3.2GB - 2 days (Awoof)",         "amount": 1000},
        {"id": "500.02",   "label": "500MB - 7 days (Direct)",        "amount": 500},
        {"id": "800.01",   "label": "1GB - 7 days (Direct)",          "amount": 800},
        {"id": "1000.03",  "label": "1.5GB - 7 days (Direct)",        "amount": 1000},
        {"id": "1500.03",  "label": "3.5GB - 7 days (Direct)",        "amount": 1500},
        {"id": "2500.01",  "label": "6GB - 7 days (Direct)",          "amount": 2500},
        {"id": "3500.01",  "label": "11GB - 7 days (Direct)",         "amount": 3500},
        {"id": "5000.01",  "label": "20GB - 7 days (Direct)",         "amount": 5000},
        {"id": "1500.02",  "label": "2GB+2mins - 30 days (Direct)",   "amount": 1500},
        {"id": "2000.01",  "label": "2.7GB+2mins - 30 days (Direct)", "amount": 2000},
        {"id": "2500.02",  "label": "3.5GB+5mins - 30 days (Direct)", "amount": 2500},
        {"id": "3500.02",  "label": "7GB - 30 days (Direct)",         "amount": 3500},
        {"id": "4500.01",  "label": "10GB+10mins - 30 days (Direct)", "amount": 4500},
        {"id": "5500.01",  "label": "12.5GB - 30 days (Direct)",      "amount": 5500},
        {"id": "6500.01",  "label": "16.5GB - 30 days (Direct)",      "amount": 6500},
        {"id": "7500.01",  "label": "20GB - 30 days (Direct)",        "amount": 7500},
        {"id": "9000.01",  "label": "25GB - 30 days (Direct)",        "amount": 9000},
        {"id": "11000.01", "label": "36GB - 30 days (Direct)",        "amount": 11000},
        {"id": "18000.01", "label": "75GB - 30 days (Direct)",        "amount": 18000},
        {"id": "35000.01", "label": "165GB - 30 days (Direct)",       "amount": 35000},
        {"id": "40000.01", "label": "150GB - 60 days (Direct)",       "amount": 40000},
        {"id": "90000.03", "label": "480GB - 90 days (Direct)",       "amount": 90000},
    ],
    "GLO": [
        {"id": "200",      "label": "200MB - 14 days (SME)",          "amount": 94},
        {"id": "500",      "label": "500MB - 7 days (SME)",           "amount": 235},
        {"id": "1000.11",  "label": "1GB - 3 days (SME)",             "amount": 282},
        {"id": "3000.11",  "label": "3GB - 3 days (SME)",             "amount": 846},
        {"id": "5000.11",  "label": "5GB - 3 days (SME)",             "amount": 1410},
        {"id": "1000.12",  "label": "1GB - 7 days (SME)",             "amount": 329},
        {"id": "3000.12",  "label": "3GB - 7 days (SME)",             "amount": 987},
        {"id": "5000.12",  "label": "5GB - 7 days (SME)",             "amount": 1645},
        {"id": "1000.21",  "label": "1GB Night - 14 days (SME)",      "amount": 329},
        {"id": "3000.21",  "label": "3GB Night - 14 days (SME)",      "amount": 987},
        {"id": "5000.21",  "label": "5GB Night - 14 days (SME)",      "amount": 1645},
        {"id": "10000.21", "label": "10GB Night - 14 days (SME)",     "amount": 3290},
        {"id": "1000",     "label": "1GB - 30 days (SME)",            "amount": 470},
        {"id": "2000",     "label": "2GB - 30 days (SME)",            "amount": 940},
        {"id": "3000",     "label": "3GB - 30 days (SME)",            "amount": 1410},
        {"id": "5000",     "label": "5GB - 30 days (SME)",            "amount": 2350},
        {"id": "10000",    "label": "10GB - 30 days (SME)",           "amount": 4700},
        {"id": "100.01",   "label": "125MB - 1 day (Awoof)",          "amount": 100},
        {"id": "200.01",   "label": "260MB - 2 days (Awoof)",         "amount": 200},
        {"id": "500.01",   "label": "1.5GB - 14 days (Direct)",       "amount": 500},
        {"id": "1000.01",  "label": "2.6GB - 30 days (Direct)",       "amount": 1000},
        {"id": "1500.01",  "label": "5GB - 30 days (Direct)",         "amount": 1500},
        {"id": "2000.01",  "label": "6.15GB - 30 days (Direct)",      "amount": 2000},
        {"id": "2500.01",  "label": "7.5GB - 30 days (Direct)",       "amount": 2500},
        {"id": "3000.01",  "label": "10GB - 30 days (Direct)",        "amount": 3000},
        {"id": "4000.01",  "label": "12.5GB - 30 days (Direct)",      "amount": 4000},
        {"id": "5000.01",  "label": "16GB - 30 days (Direct)",        "amount": 5000},
        {"id": "8000.01",  "label": "28GB - 30 days (Direct)",        "amount": 8000},
        {"id": "10000.01", "label": "38GB - 30 days (Direct)",        "amount": 10000},
        {"id": "15000.01", "label": "64GB - 30 days (Direct)",        "amount": 15000},
        {"id": "20000.01", "label": "107GB - 30 days (Direct)",       "amount": 20000},
        {"id": "500.02",   "label": "2GB - 1 day (Awoof)",            "amount": 500},
        {"id": "1500.02",  "label": "6GB - 7 days (Direct)",          "amount": 1500},
        {"id": "500.03",   "label": "2.5GB Weekend [Sat&Sun] (Awoof)","amount": 500},
        {"id": "200.02",   "label": "875MB Weekend [Sun] (Awoof)",    "amount": 200},
        {"id": "30000.01", "label": "165GB - 30 days (Direct)",       "amount": 30000},
        {"id": "36000.01", "label": "220GB - 30 days (Direct)",       "amount": 40000},
        {"id": "50000.01", "label": "320GB - 30 days (Direct)",       "amount": 50000},
        {"id": "60000.01", "label": "380GB - 30 days (Direct)",       "amount": 60000},
        {"id": "75000.01", "label": "475GB - 30 days (Direct)",       "amount": 75000},
        {"id": "150000.03","label": "1TB - 365 days (Direct)",        "amount": 150000},
    ],
    "AIRTEL": [
        {"id": "499.91",   "label": "1GB - 1 day (Awoof)",            "amount": 500},
        {"id": "599.91",   "label": "1.5GB - 2 days (Awoof)",         "amount": 600},
        {"id": "749.91",   "label": "2GB - 2 days (Awoof)",           "amount": 750},
        {"id": "999.91",   "label": "3GB - 2 days (Awoof)",           "amount": 1000},
        {"id": "1499.91",  "label": "5GB - 2 days (Awoof)",           "amount": 1500},
        {"id": "499.92",   "label": "500MB - 7 days (Direct)",        "amount": 500},
        {"id": "799.91",   "label": "1GB - 7 days (Direct)",          "amount": 800},
        {"id": "999.92",   "label": "1.5GB - 7 days (Direct)",        "amount": 1000},
        {"id": "1499.92",  "label": "3.5GB - 7 days (Direct)",        "amount": 1500},
        {"id": "2499.91",  "label": "6GB - 7 days (Direct)",          "amount": 2500},
        {"id": "2999.91",  "label": "10GB - 7 days (Direct)",         "amount": 3000},
        {"id": "4999.91",  "label": "18GB - 7 days (Direct)",         "amount": 5000},
        {"id": "1499.93",  "label": "2GB - 30 days (Direct)",         "amount": 1500},
        {"id": "1999.91",  "label": "3GB - 30 days (Direct)",         "amount": 2000},
        {"id": "2499.92",  "label": "4GB - 30 days (Direct)",         "amount": 2500},
        {"id": "2999.92",  "label": "8GB - 30 days (Direct)",         "amount": 3000},
        {"id": "3999.91",  "label": "10GB - 30 days (Direct)",        "amount": 4000},
        {"id": "4999.92",  "label": "13GB - 30 days (Direct)",        "amount": 5000},
        {"id": "5999.91",  "label": "18GB - 30 days (Direct)",        "amount": 6000},
        {"id": "7999.91",  "label": "25GB - 30 days (Direct)",        "amount": 8000},
        {"id": "9999.91",  "label": "35GB - 30 days (Direct)",        "amount": 10000},
        {"id": "14999.91", "label": "60GB - 30 days (Direct)",        "amount": 15000},
        {"id": "19999.91", "label": "100GB - 30 days (Direct)",       "amount": 20000},
        {"id": "29999.91", "label": "160GB - 30 days (Direct)",       "amount": 30000},
        {"id": "39999.91", "label": "210GB - 30 days (Direct)",       "amount": 40000},
        {"id": "49999.91", "label": "300GB - 90 days (Direct)",       "amount": 50000},
        {"id": "59999.91", "label": "350GB - 90 days (Direct)",       "amount": 60000},
    ],
    "9MOBILE": [
        {"id": "50",       "label": "50MB - 30 days (SME)",           "amount": 23},
        {"id": "100",      "label": "100MB - 30 days (SME)",          "amount": 46},
        {"id": "300",      "label": "300MB - 30 days (SME)",          "amount": 138},
        {"id": "500",      "label": "500MB - 30 days (SME)",          "amount": 225},
        {"id": "1000",     "label": "1GB - 30 days (SME)",            "amount": 450},
        {"id": "2000",     "label": "2GB - 30 days (SME)",            "amount": 900},
        {"id": "3000",     "label": "3GB - 30 days (SME)",            "amount": 1350},
        {"id": "4000",     "label": "4GB - 30 days (SME)",            "amount": 1800},
        {"id": "5000",     "label": "5GB - 30 days (SME)",            "amount": 2250},
        {"id": "10000",    "label": "10GB - 30 days (SME)",           "amount": 4500},
        {"id": "15000",    "label": "15GB - 30 days (SME)",           "amount": 6750},
        {"id": "20000",    "label": "20GB - 30 days (SME)",           "amount": 9000},
        {"id": "25000",    "label": "25GB - 30 days (SME)",           "amount": 11250},
        {"id": "100.01",   "label": "100MB - 1 day (Awoof)",          "amount": 100},
        {"id": "150.01",   "label": "180MB - 1 day (Awoof)",          "amount": 150},
        {"id": "200.01",   "label": "250MB - 1 day (Awoof)",          "amount": 200},
        {"id": "350.01",   "label": "450MB - 1 day (Awoof)",          "amount": 350},
        {"id": "500.01",   "label": "650MB - 3 days (Awoof)",         "amount": 500},
        {"id": "1500.01",  "label": "1.75GB - 7 days (Direct)",       "amount": 1500},
        {"id": "600.01",   "label": "650MB - 14 days (Direct)",       "amount": 600},
        {"id": "1000.01",  "label": "1.1GB - 30 days (Direct)",       "amount": 1000},
        {"id": "1200.01",  "label": "1.4GB - 30 days (Direct)",       "amount": 1200},
        {"id": "2000.01",  "label": "2.44GB - 30 days (Direct)",      "amount": 2000},
        {"id": "2500.01",  "label": "3.17GB - 30 days (Direct)",      "amount": 2500},
        {"id": "3000.01",  "label": "3.91GB - 30 days (Direct)",      "amount": 3000},
        {"id": "4000.01",  "label": "5.10GB - 30 days (Direct)",      "amount": 4000},
        {"id": "5000.01",  "label": "6.5GB - 30 days (Direct)",       "amount": 5000},
        {"id": "12000.01", "label": "16GB - 30 days (Direct)",        "amount": 12000},
        {"id": "18500.01", "label": "24.3GB - 30 days (Direct)",      "amount": 18500},
        {"id": "20000.01", "label": "26.5GB - 30 days (Direct)",      "amount": 20000},
        {"id": "30000.01", "label": "39GB - 60 days (Direct)",        "amount": 30000},
        {"id": "60000.01", "label": "78GB - 90 days (Direct)",        "amount": 60000},
        {"id": "150000.01","label": "190GB - 180 days (Direct)",      "amount": 150000},
    ],
}


# =========================
# BEEWAVE SPECIAL BUNDLE PLANS
# These are cheaper plans via Beewave API.
# Add BEEWAVE_API_KEY=your_key to your .env
# =========================

BEEWAVE_PLANS = {
    "MTN": [
        {"qty": "500mb",  "label": "MTN 500MB (Special)",  "amount": 150},
        {"qty": "1gb",    "label": "MTN 1GB (Special)",    "amount": 263},
        {"qty": "2gb",    "label": "MTN 2GB (Special)",    "amount": 500},
        {"qty": "3gb",    "label": "MTN 3GB (Special)",    "amount": 720},
        {"qty": "5gb",    "label": "MTN 5GB (Special)",    "amount": 1150},
        {"qty": "10gb",   "label": "MTN 10GB (Special)",   "amount": 2200},
    ],
    "GLO": [
        {"qty": "500mb",  "label": "GLO 500MB (Special)",  "amount": 120},
        {"qty": "1gb",    "label": "GLO 1GB (Special)",    "amount": 230},
        {"qty": "2gb",    "label": "GLO 2GB (Special)",    "amount": 450},
        {"qty": "5gb",    "label": "GLO 5GB (Special)",    "amount": 1000},
    ],
    "AIRTEL": [
        {"qty": "500mb",  "label": "Airtel 500MB (Special)", "amount": 140},
        {"qty": "1gb",    "label": "Airtel 1GB (Special)",   "amount": 260},
        {"qty": "2gb",    "label": "Airtel 2GB (Special)",   "amount": 500},
        {"qty": "5gb",    "label": "Airtel 5GB (Special)",   "amount": 1100},
    ],
    "9MOBILE": [
        {"qty": "500mb",  "label": "9Mobile 500MB (Special)", "amount": 130},
        {"qty": "1gb",    "label": "9Mobile 1GB (Special)",   "amount": 240},
        {"qty": "2gb",    "label": "9Mobile 2GB (Special)",   "amount": 460},
    ],
}

# Network names Beewave expects (lowercase)
BEEWAVE_NETWORK_NAMES = {
    "MTN":     "mtn",
    "GLO":     "glo",
    "AIRTEL":  "airtel",
    "9MOBILE": "9mobile",
}


# =========================
# SMM SERVICES
# =========================

SMM_SERVICES = {
    "instagram": [
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Instagram Followers", "min": 100,  "max": 100000, "amount": 2000},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Instagram Likes",     "min": 50,   "max": 50000,  "amount": 500},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Instagram Views",     "min": 100,  "max": 500000, "amount": 300},
    ],
    "tiktok": [
        {"id": "10019", "label": "TikTok Views [Fast - 5M/Day]",         "min": 50,  "max": 2147483647, "amount": 300},
        {"id": "2260",  "label": "TikTok Views [Faster - 10M/Day]",      "min": 50,  "max": 2147483647, "amount": 350},
        {"id": "10168", "label": "TikTok Views [10M/Day - No Refill]",   "min": 100, "max": 2147483647, "amount": 370},
        {"id": "10169", "label": "TikTok Views [30 Day Refill - 10M/D]", "min": 100, "max": 2147483647, "amount": 400},
        {"id": "10170", "label": "TikTok Views [90 Day Refill - 10M/D]", "min": 100, "max": 2147483647, "amount": 450},
        {"id": "10120", "label": "TikTok Views [5M/Day - No Refill]",    "min": 50,  "max": 2147483647, "amount": 320},
        {"id": "10020", "label": "TikTok Views [30D Refill - 5M/Day]",   "min": 50,  "max": 2147483647, "amount": 380},
        {"id": "8526",  "label": "TikTok Views [30D Refill - Fast]",     "min": 100, "max": 10000000,   "amount": 420},
    ],
    "youtube": [
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "YouTube Views",       "min": 500, "max": 500000, "amount": 200},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "YouTube Subscribers", "min": 50,  "max": 10000,  "amount": 600},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "YouTube Likes",       "min": 50,  "max": 50000,  "amount": 250},
    ],
    "facebook": [
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Facebook Page Likes",  "min": 100, "max": 50000,  "amount": 400},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Facebook Post Likes",  "min": 100, "max": 50000,  "amount": 200},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Facebook Followers",   "min": 100, "max": 50000,  "amount": 350},
        {"id": "REPLACE_WITH_REAL_JAP_ID", "label": "Facebook Video Views", "min": 500, "max": 500000, "amount": 150},
    ],
}


# =========================
# WEB PAGES
# =========================

@login_required
def home(request):
    account             = get_or_create_account(request.user)
    recent_transactions = Transaction.objects.filter(
        user=request.user
    ).order_by("-created_at")[:5]
    context = {
        "account":             account,
        "recent_transactions": recent_transactions,
        "total_deposits":    Transaction.objects.filter(
            user=request.user, transaction_type="deposit", status="successful"
        ).count(),
        "total_withdrawals": Transaction.objects.filter(
            user=request.user, transaction_type="withdraw", status="successful"
        ).count(),
        "total_data": DataPurchase.objects.filter(
            user=request.user, status="successful"
        ).count(),
        "total_smm": SMMOrder.objects.filter(
            user=request.user, status="completed"
        ).count(),
    }
    return render(request, "home.html", context)


@login_required
def payment(request):
    account      = get_or_create_account(request.user)
    transactions = Transaction.objects.filter(
        user=request.user
    ).order_by("-created_at")[:10]
    detail, _ = Detail.objects.get_or_create(user=request.user)
    context = {
        "account":            account,
        "transactions":       transactions,
        "detail":             detail,
        "data_plans_json":    json.dumps(DATA_PLANS),
        "beewave_plans_json": json.dumps(BEEWAVE_PLANS),
    }
    return render(request, "payment.html", context)


@login_required
def report(request):
    transactions   = Transaction.objects.filter(user=request.user).order_by("-created_at")
    data_purchases = DataPurchase.objects.filter(user=request.user).order_by("-created_at")
    smm_orders     = SMMOrder.objects.filter(user=request.user).order_by("-created_at")
    context = {
        "transactions":   transactions,
        "data_purchases": data_purchases,
        "smm_orders":     smm_orders,
    }
    return render(request, "report.html", context)


@login_required
def success(request):
    return render(request, "success.html")

@login_required
def succed_data(request):
    return render(request, "succed_data.html")

@login_required
def succed_trans(request):
    return render(request, "succed_trans.html")

def low_balance(request):
    return render(request, "low_balance.html")

def transfer(request):
    return render(request, "transfer.html")


# =========================
# PROFILE (DRF)
# =========================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_profile(request):
    detail, _ = Detail.objects.get_or_create(user=request.user)
    return Response(DetailSerializer(detail).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_profile(request):
    detail, _ = Detail.objects.get_or_create(user=request.user)
    serializer = DetailSerializer(detail, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


# =========================
# AUTH API
# =========================

@api_view(["POST"])
def api_login(request):
    user = authenticate(
        username=request.data.get("username"),
        password=request.data.get("password"),
    )
    if not user:
        return Response({"error": "Invalid credentials"}, status=400)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key})


# =========================
# WALLET API
# =========================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def withdraw(request):
    account_number = request.data.get("account_number")
    amount_raw     = request.data.get("amount")

    if not account_number or not amount_raw:
        return Response({"error": "account_number and amount are required."}, status=400)

    try:
        account = Account.objects.get(account_number=account_number)
        amount  = Decimal(str(amount_raw))
    except (Account.DoesNotExist, InvalidOperation):
        return Response({"error": "Invalid account number or amount."}, status=400)

    if amount <= 0:
        return Response({"error": "Amount must be positive."}, status=400)

    if account.balance < amount:
        return Response({"error": "Insufficient balance."}, status=400)

    account.balance -= amount
    account.save()

    Transaction.objects.create(
        user=account.user, account=account,
        amount=amount, transaction_type="withdraw", status="successful",
    )
    return Response({"message": "Withdrawal successful.", "balance": str(account.balance)})


# =========================
# DEPOSIT (WEB)
# =========================

@login_required
def deposit(request):
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("payment")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("payment")

        account = get_or_create_account(request.user)
        ref     = str(uuid.uuid4())

        transaction = Transaction.objects.create(
            user=request.user, account=account,
            amount=amount, transaction_type="deposit",
            status="pending", reference=ref,
        )

        site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
        payload  = {
            "tx_ref":       ref,
            "amount":       str(amount),
            "currency":     "NGN",
            "redirect_url": f"{site_url}/payment_success/",
            "customer": {
                "email": request.user.email or f"{request.user.username}@placeholder.com",
                "name":  request.user.get_full_name() or request.user.username,
            },
            "customizations": {
                "title":       "Wallet Deposit",
                "description": f"Deposit NGN{amount} into your wallet",
            },
        }

        try:
            resp      = requests.post(
                "https://api.flutterwave.com/v3/payments",
                json=payload, headers=flw_headers(), timeout=10,
            )
            resp_data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Flutterwave initiation error: {e}")
            transaction.status = "failed"
            transaction.save()
            messages.error(request, "Could not connect to payment provider.")
            return redirect("payment")

        if resp_data.get("status") == "success":
            return redirect(resp_data["data"]["link"])

        logger.error(f"Flutterwave error response: {resp_data}")
        transaction.status = "failed"
        transaction.save()
        messages.error(request, "Payment initiation failed. Please try again.")
        return redirect("payment")

    return redirect("payment")


# =========================
# PAYMENT SUCCESS
# =========================

@login_required
def payment_success(request):
    status         = request.GET.get("status")
    transaction_id = request.GET.get("transaction_id")
    tx_ref         = request.GET.get("tx_ref")

    if status == "cancelled":
        messages.error(request, "Payment was cancelled.")
        return redirect("payment")

    if status not in ("successful", "completed") or not transaction_id or not tx_ref:
        messages.error(request, "Payment incomplete. Contact support if money was deducted.")
        return redirect("payment")

    try:
        transaction_obj = Transaction.objects.get(reference=tx_ref)
    except Transaction.DoesNotExist:
        messages.error(request, f"Transaction record not found for ref: {tx_ref}")
        return redirect("payment")

    if transaction_obj.status == "successful":
        messages.success(request, "Deposit already processed.")
        return redirect("home")

    try:
        resp = requests.get(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
            headers=flw_headers(), timeout=10,
        )
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Flutterwave verify error: {e}")
        messages.error(request, "Could not verify payment. Contact support.")
        return redirect("payment")

    flw_data = data.get("data", {})

    if (
        data.get("status") == "success"
        and flw_data.get("status") in ("successful", "completed")
        and flw_data.get("tx_ref") == tx_ref
    ):
        if credit_account(transaction_obj):
            messages.success(request, f"₦{transaction_obj.amount:,} deposited successfully.")
        return redirect("home")

    messages.error(request, "Payment verification failed. Contact support.")
    return redirect("payment")


# =========================
# TRANSACTION (withdraw + transfer)
# =========================

@login_required
def transaction(request):
    if request.method == "POST":
        tx_type = request.POST.get("transaction_type")

        if tx_type == "deposit":
            return deposit(request)

        elif tx_type == "withdraw":
            try:
                amount = Decimal(request.POST.get("amount", "0"))
            except InvalidOperation:
                messages.error(request, "Invalid amount.")
                return redirect("payment")

            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect("payment")

            account = get_or_create_account(request.user)
            if account.balance < amount:
                return redirect("low_balance")

            account.balance -= amount
            account.save()
            Transaction.objects.create(
                user=request.user, account=account,
                amount=amount, transaction_type="withdraw", status="successful",
            )
            messages.success(request, f"₦{amount:,} successfully withdrawn.")
            return redirect("succed_trans")

        elif tx_type == "transfer":
            receiver_no = request.POST.get("receiver", "").strip()
            try:
                amount = Decimal(request.POST.get("amount", "0"))
            except InvalidOperation:
                messages.error(request, "Invalid amount.")
                return redirect("payment")

            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect("payment")

            if not receiver_no:
                messages.error(request, "Please enter a recipient account number.")
                return redirect("payment")

            sender = get_or_create_account(request.user)

            try:
                receiver = Account.objects.get(account_number=receiver_no)
            except Account.DoesNotExist:
                messages.error(request, "Recipient account not found.")
                return redirect("payment")

            if receiver.user == request.user:
                messages.error(request, "You cannot transfer to your own account.")
                return redirect("payment")

            if sender.balance < amount:
                return redirect("low_balance")

            with db_transaction.atomic():
                sender.balance   -= amount
                receiver.balance += amount
                sender.save()
                receiver.save()
                Transaction.objects.create(
                    user=request.user, account=sender,
                    amount=amount, transaction_type="transfer", status="successful",
                )

            messages.success(request, f"₦{amount:,} transferred successfully.")
            return redirect("succed_trans")

    return redirect("payment")


# =========================
# CLUBKONNECT API
# =========================

def call_clubkonnect_data_api(network, phone, plan_id, request_id):
    user_id      = config("CLUBKONNECT_USER_ID")
    api_key      = config("CLUBKONNECT_API_KEY")
    network_code = NETWORK_CODES.get(network)

    if not network_code:
        return False, f"Unknown network: {network}"

    url    = "https://www.nellobytesystems.com/APIDatabundleV1.asp"
    params = {
        "UserID":        user_id,
        "APIKey":        api_key,
        "MobileNetwork": network_code,
        "DataPlan":      plan_id,
        "MobileNumber":  phone,
        "RequestID":     request_id,
        "CallBackURL":   "",
    }

    logger.info(f"ClubKonnect → network={network_code} plan={plan_id} phone={phone}")

    try:
        response = requests.get(url, params=params, timeout=15)
        text     = response.text.strip()
        logger.info(f"ClubKonnect response: {text}")

        try:
            json_resp   = json.loads(text)
            status      = json_resp.get("status", "")
            status_code = str(json_resp.get("statuscode", ""))

            if status == "ORDER_RECEIVED" or status_code == "100":
                return True, text
            elif status == "INSUFFICIENT_BALANCE":
                return False, "insufficient balance in provider wallet"
            elif status in ("INVALID_APIKEY", "INVALID_USERID"):
                return False, "invalid api key or user id"
            elif status == "INVALID_MOBILENUMBER":
                return False, "invalid number"
            else:
                logger.error(f"ClubKonnect error: {text}")
                return False, text

        except json.JSONDecodeError:
            if "successful" in text.lower() or "success" in text.lower():
                return True, text
            else:
                logger.error(f"ClubKonnect plain text error: {text}")
                return False, text

    except requests.RequestException as e:
        logger.error(f"ClubKonnect request failed: {e}")
        return False, "Network error contacting ClubKonnect."


# =========================
# BEEWAVE API
# =========================

def call_beewave_data_api(network, phone, qty):
    """
    Call Beewave data API.
    Returns (True, reference) on success, (False, error_message) on failure.
    POST to https://beewave.ng/api/data.php
    """
    api_key      = config("BEEWAVE_API_KEY")
    network_name = BEEWAVE_NETWORK_NAMES.get(network)

    if not network_name:
        return False, f"Unknown network: {network}"

    payload = {
        "api_key":      api_key,
        "type":         "sme-data",
        "qty":          qty,           # e.g. "1gb", "500mb"
        "network":      network_name,  # e.g. "mtn", "glo"
        "phone_number": phone,
    }

    logger.info(f"Beewave → network={network_name} qty={qty} phone={phone}")

    try:
        response = requests.post(
            "https://beewave.ng/api/data.php",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        data = response.json()
        logger.info(f"Beewave response: {data}")

        status = data.get("status", "")

        if status == "success":
            return True, data.get("reference", "")
        elif status == "pending":
            # Pending still means order was accepted
            return True, data.get("reference", "pending")
        else:
            error_msg = data.get("desc", "Transaction failed")
            logger.error(f"Beewave error: {data}")
            return False, error_msg

    except requests.RequestException as e:
        logger.error(f"Beewave request failed: {e}")
        return False, "Network error contacting Beewave."
    except (ValueError, KeyError) as e:
        logger.error(f"Beewave response parse error: {e}")
        return False, "Invalid response from Beewave."


# =========================
# BUY DATA — CLUBKONNECT (WEB)
# =========================

@login_required
def buy_data(request):
    if request.method == "POST":
        network = request.POST.get("network", "").strip().upper()
        phone   = request.POST.get("phone_number", "").strip()
        plan_id = request.POST.get("product_code", "").strip()

        if not network or not phone or not plan_id:
            messages.error(request, "Network, phone number, and data plan are required.")
            return redirect("buy_data")

        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number.")
            return redirect("buy_data")

        network_plans = DATA_PLANS.get(network, [])
        plan_info     = next((p for p in network_plans if p["id"] == plan_id), None)

        if not plan_info:
            messages.error(request, "Invalid data plan selected.")
            return redirect("buy_data")

        amount = Decimal(str(plan_info["amount"]))

        try:
            account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if account.balance < amount:
            return redirect("low_balance")

        account.balance -= amount
        account.save()

        request_id = str(uuid.uuid4()).replace("-", "")[:20]

        try:
            success_flag, ck_response = call_clubkonnect_data_api(
                network, phone, plan_id, request_id
            )
        except Exception as e:
            account.balance += amount
            account.save()
            logger.error(f"buy_data crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("buy_data")

        if success_flag:
            DataPurchase.objects.create(
                user=request.user, network=network,
                phone_number=phone, amount=amount,
                status="successful", reference=request_id,
            )
            messages.success(request, f"{plan_info['label']} purchased successfully for {phone}.")
            return redirect("succed_data")

        else:
            account.balance += amount
            account.save()

            if "insufficient" in ck_response.lower():
                error_msg = "Our data provider balance is low. Please try again later."
            elif "invalid api" in ck_response.lower():
                error_msg = "API configuration error. Please contact support."
            elif "invalid number" in ck_response.lower():
                error_msg = "Invalid phone number. Please check and try again."
            else:
                error_msg = f"Purchase failed: {ck_response}. Your balance has been refunded."

            messages.error(request, error_msg)
            DataPurchase.objects.create(
                user=request.user, network=network,
                phone_number=phone, amount=amount,
                status="failed", reference=request_id,
            )
            return redirect("buy_data")

    context = {
        "data_plans_json": json.dumps(DATA_PLANS),
        "networks":        list(DATA_PLANS.keys()),
    }
    return render(request, "buy_data.html", context)


# =========================
# BUY SPECIAL BUNDLE — BEEWAVE (WEB)
# =========================

@login_required
def buy_special_bundle(request):
    """Handle Beewave special bundle data purchases."""
    if request.method == "POST":
        network = request.POST.get("network", "").strip().upper()
        phone   = request.POST.get("phone_number", "").strip()
        qty     = request.POST.get("qty", "").strip()      # e.g. "1gb", "500mb"

        if not network or not phone or not qty:
            messages.error(request, "Network, phone number, and data plan are required.")
            return redirect("payment")

        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number.")
            return redirect("payment")

        # Find plan info from BEEWAVE_PLANS
        network_plans = BEEWAVE_PLANS.get(network, [])
        plan_info     = next((p for p in network_plans if p["qty"] == qty), None)

        if not plan_info:
            messages.error(request, "Invalid data plan selected.")
            return redirect("payment")

        amount = Decimal(str(plan_info["amount"]))

        try:
            account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if account.balance < amount:
            return redirect("low_balance")

        # Deduct BEFORE calling API
        account.balance -= amount
        account.save()

        try:
            success_flag, bw_response = call_beewave_data_api(network, phone, qty)
        except Exception as e:
            account.balance += amount
            account.save()
            logger.error(f"buy_special_bundle crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("payment")

        if success_flag:
            DataPurchase.objects.create(
                user=request.user,
                network=network,
                phone_number=phone,
                amount=amount,
                status="successful",
                reference=str(bw_response),
            )
            messages.success(
                request, f"{plan_info['label']} purchased successfully for {phone}."
            )
            return redirect("succed_data")

        else:
            # Refund on failure
            account.balance += amount
            account.save()

            if "insufficient" in bw_response.lower():
                error_msg = "Our data provider balance is low. Please try again later."
            elif "invalid" in bw_response.lower():
                error_msg = "Invalid request. Please check your details and try again."
            else:
                error_msg = f"Purchase failed: {bw_response}. Your balance has been refunded."

            messages.error(request, error_msg)
            DataPurchase.objects.create(
                user=request.user,
                network=network,
                phone_number=phone,
                amount=amount,
                status="failed",
                reference=str(uuid.uuid4()).replace("-", "")[:20],
            )
            return redirect("payment")

    return redirect("payment")


# =========================
# JAP SMM API
# =========================

def call_jap_api(action, extra_params=None):
    api_key = config("JAP_API_KEY")
    url     = "https://justanotherpanel.com/api/v2"
    params  = {"key": api_key, "action": action}

    if extra_params:
        params.update(extra_params)

    try:
        response = requests.post(url, data=params, timeout=15)
        result   = response.json()
        logger.info(f"JAP response: {result}")
        return result
    except Exception as e:
        logger.error(f"JAP API error: {e}")
        return None


# =========================
# MARKET / SMM PAGE
# =========================

@login_required
def market(request):
    account           = get_or_create_account(request.user)
    recent_smm_orders = SMMOrder.objects.filter(
        user=request.user
    ).order_by("-created_at")[:10]
    context = {
        "account":           account,
        "smm_services_json": json.dumps(SMM_SERVICES),
        "platforms":         list(SMM_SERVICES.keys()),
        "recent_orders":     recent_smm_orders,
    }
    return render(request, "market.html", context)


@login_required
def buy_smm(request):
    if request.method == "POST":
        platform   = request.POST.get("platform", "").strip().lower()
        service_id = request.POST.get("service_id", "").strip()
        link       = request.POST.get("link", "").strip()
        quantity   = request.POST.get("quantity", "0").strip()

        if not platform or not service_id or not link or not quantity:
            messages.error(request, "All fields are required.")
            return redirect("market")

        try:
            quantity = int(quantity)
        except ValueError:
            messages.error(request, "Invalid quantity.")
            return redirect("market")

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than zero.")
            return redirect("market")

        platform_services = SMM_SERVICES.get(platform, [])
        service_info      = next(
            (s for s in platform_services if s["id"] == service_id), None
        )

        if not service_info:
            messages.error(request, "Invalid service selected.")
            return redirect("market")

        if quantity < service_info["min"] or quantity > service_info["max"]:
            messages.error(
                request,
                f"Quantity must be between {service_info['min']} and {service_info['max']}."
            )
            return redirect("market")

        # Price is per 1000 units
        amount = Decimal(str(service_info["amount"])) * Decimal(quantity) / Decimal(1000)
        amount = amount.quantize(Decimal("0.01"))

        try:
            account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if account.balance < amount:
            return redirect("low_balance")

        account.balance -= amount
        account.save()

        try:
            result = call_jap_api("add", {
                "service":  service_id,
                "link":     link,
                "quantity": quantity,
            })
        except Exception as e:
            account.balance += amount
            account.save()
            logger.error(f"JAP API crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("market")

        if result and "order" in result:
            jap_order_id = str(result["order"])

            SMMOrder.objects.create(
                user=request.user,
                platform=platform,
                service_name=service_info["label"],
                service_id=service_id,
                link=link,
                quantity=quantity,
                amount=amount,
                jap_order_id=jap_order_id,
                status="processing",
            )

            Transaction.objects.create(
                user=request.user,
                account=account,
                amount=amount,
                transaction_type="smm",
                status="successful",
                description=f"{service_info['label']} x{quantity}",
            )

            messages.success(
                request,
                f"Order placed! {service_info['label']} x{quantity} is now processing."
            )
            return redirect("market")

        else:
            account.balance += amount
            account.save()

            error_detail = result.get("error", "Unknown error") if result else "No response"
            logger.error(f"JAP order failed: {error_detail}")

            SMMOrder.objects.create(
                user=request.user,
                platform=platform,
                service_name=service_info["label"],
                service_id=service_id,
                link=link,
                quantity=quantity,
                amount=amount,
                status="failed",
            )

            messages.error(
                request,
                f"Order failed: {error_detail}. Your balance has been refunded."
            )
            return redirect("market")

    return redirect("market")


@login_required
def check_smm_order(request, order_id):
    try:
        order = SMMOrder.objects.get(id=order_id, user=request.user)
    except SMMOrder.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect("market")

    if not order.jap_order_id:
        messages.error(request, "No JAP order ID found for this order.")
        return redirect("market")

    result = call_jap_api("status", {"order": order.jap_order_id})

    if result and "status" in result:
        jap_status = result["status"].lower()
        status_map = {
            "completed":   "completed",
            "partial":     "partial",
            "cancelled":   "cancelled",
            "processing":  "processing",
            "pending":     "pending",
            "in progress": "processing",
        }
        order.status = status_map.get(jap_status, "processing")
        order.save()
        messages.success(request, f"Order status updated: {order.status.title()}")
    else:
        messages.error(request, "Could not fetch order status. Try again later.")

    return redirect("market")


# =========================
# FLUTTERWAVE WEBHOOK
# =========================

@csrf_exempt
def flutterwave_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    secret_hash = config("FLW_WEBHOOK_SECRET", default="")
    signature   = request.headers.get("verif-hash", "")

    if secret_hash and signature != secret_hash:
        logger.warning("Flutterwave webhook: invalid signature.")
        return JsonResponse({"error": "Unauthorized."}, status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    if payload.get("event") == "charge.completed":
        data = payload.get("data", {})
        if data.get("status") == "successful":
            tx_ref = data.get("tx_ref")
            try:
                transaction_obj = Transaction.objects.get(reference=tx_ref)
            except Transaction.DoesNotExist:
                logger.error(f"Webhook: transaction not found for tx_ref={tx_ref}")
                return JsonResponse({"status": "ok"})

            credited = credit_account(transaction_obj)
            logger.info(
                f"Webhook: tx_ref={tx_ref} "
                f"{'credited' if credited else 'already processed'}."
            )

    return JsonResponse({"status": "ok"})


# =========================
# REPORT
# =========================

def report_view(request):
    if request.method == "POST":
        message = request.POST.get("message")
        Report.objects.create(message=message)
        messages.success(request, "Report sent!")
        return redirect("report")
    return render(request, "report.html")