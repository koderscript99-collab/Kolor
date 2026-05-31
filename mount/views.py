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

from .models import Account, Transaction, Detail, DataPurchase, Report, SMMOrder, ForeignNumber, ElectricityPurchase, CableTVPurchase
from .serializers import DetailSerializer

logger = logging.getLogger(__name__)


# =========================
# HELPERS
# =========================

def get_or_create_account(user):
    account, _ = Account.objects.get_or_create(user=user)
    return account


def get_owner_account():
    """
    Returns the site owner's Account.
    Set SITE_OWNER_USERNAME=yourusername in your .env file.
    This account is used to fund API calls (ClubKonnect, Beewave, 5SIM).
    Flow: customer balance deducted → owner account credited → API called → owner refunded if API fails.
    """
    username = config("SITE_OWNER_USERNAME")
    try:
        user    = User.objects.get(username=username)
        account = Account.objects.get(user=user)
        return account
    except (User.DoesNotExist, Account.DoesNotExist):
        logger.error(f"Owner account not found for username: {username}")
        raise Exception(f"Site owner account '{username}' not found. Check SITE_OWNER_USERNAME in .env")


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
# =========================

# ── BEEWAVE PLANS ────────────────────────────────────────────────────────────
# qty values must match Beewave's exact product codes from your pricing table.
# type field per network:
#   MTN       → "sme-data"
#   GLO       → "cg-data"  (SME plans) or "sme-data" for weekly
#   9MOBILE   → "cg-data"
#   AIRTEL    → "direct-gifting-data"
# Prices below are your selling price (add your margin on top of API Earner cost).
# API Earner costs shown in comments so you know your profit per plan.

BEEWAVE_PLANS = {
    "MTN": [
        # sme-data plans
        {"qty": "500mb_weekly",  "type": "sme-data", "label": "MTN 500MB - 7 days",   "amount": 390},   # cost ₦325
        {"qty": "1gb_weekly",    "type": "sme-data", "label": "MTN 1GB - 7 days",     "amount": 530},   # cost ₦440
        {"qty": "2gb_weekly",    "type": "sme-data", "label": "MTN 2GB - 7 days",     "amount": 980},   # cost ₦820
        {"qty": "3gb_weekly",    "type": "sme-data", "label": "MTN 3GB - 7 days",     "amount": 1350},  # cost ₦1170
        {"qty": "1gb_monthly",   "type": "sme-data", "label": "MTN 1GB - 30 days",    "amount": 650},   # cost ₦550
        {"qty": "2gb_monthly",   "type": "sme-data", "label": "MTN 2GB - 30 days",    "amount": 1150},  # cost ₦990
        {"qty": "3gb_monthly",   "type": "sme-data", "label": "MTN 3GB - 30 days",    "amount": 1700},  # cost ₦1450
        {"qty": "5gb_monthly",   "type": "sme-data", "label": "MTN 5GB - 30 days",    "amount": 2050},  # cost ₦1750
    ],
    "GLO": [
        # cg-data plans
        {"qty": "200mb_weekly",  "type": "cg-data",  "label": "GLO 200MB - 7 days",   "amount": 140},   # cost ₦109
        {"qty": "1gb_3days",     "type": "cg-data",  "label": "GLO 1GB - 3 days",     "amount": 330},   # cost ₦277
        {"qty": "1gb_7days",     "type": "cg-data",  "label": "GLO 1GB - 7 days",     "amount": 380},   # cost ₦317
        {"qty": "3gb_3days",     "type": "cg-data",  "label": "GLO 3GB - 3 days",     "amount": 950},   # cost ₦801
        {"qty": "3gb_7days",     "type": "cg-data",  "label": "GLO 3GB - 7 days",     "amount": 1100},  # cost ₦920
        {"qty": "500mb_monthly", "type": "cg-data",  "label": "GLO 500MB - 30 days",  "amount": 280},   # cost ₦228
        {"qty": "1gb_monthly",   "type": "cg-data",  "label": "GLO 1GB - 30 days",    "amount": 520},   # cost ₦430
        {"qty": "2gb_monthly",   "type": "cg-data",  "label": "GLO 2GB - 30 days",    "amount": 990},   # cost ₦840
        {"qty": "5gb_monthly",   "type": "cg-data",  "label": "GLO 5GB - 30 days",    "amount": 2400},  # cost ₦2075
    ],
    "AIRTEL": [
        # direct-gifting-data plans
        {"qty": "150mb_daily",   "type": "direct-gifting-data", "label": "Airtel 150MB - 1 day",   "amount": 100},  # cost ₦70
        {"qty": "300mb_2days",   "type": "direct-gifting-data", "label": "Airtel 300MB - 2 days",  "amount": 150},  # cost ₦115
        {"qty": "600mb_2days",   "type": "direct-gifting-data", "label": "Airtel 600MB - 2 days",  "amount": 270},  # cost ₦220
        {"qty": "1.5gb_1days",   "type": "direct-gifting-data", "label": "Airtel 1.5GB - 1 day",   "amount": 550},  # cost ₦460
        {"qty": "2gb_2days",     "type": "direct-gifting-data", "label": "Airtel 2GB - 2 days",    "amount": 650},  # cost ₦560
        {"qty": "3gb_2days",     "type": "direct-gifting-data", "label": "Airtel 3GB - 2 days",    "amount": 900},  # cost ₦800
        {"qty": "10gb_monthly",  "type": "direct-gifting-data", "label": "Airtel 10GB - 30 days",  "amount": 3500}, # cost ₦3100
    ],
    "9MOBILE": [
        # cg-data plans
        {"qty": "500mb_weekly",  "type": "cg-data",  "label": "9Mobile 500MB - 7 days",  "amount": 360},  # cost ₦300
        {"qty": "1gb_monthly",   "type": "cg-data",  "label": "9Mobile 1GB - 30 days",   "amount": 650},  # cost ₦550
        {"qty": "1.5gb_monthly", "type": "cg-data",  "label": "9Mobile 1.5GB - 30 days", "amount": 950},  # cost ₦800
        {"qty": "3gb_monthly",   "type": "cg-data",  "label": "9Mobile 3GB - 30 days",   "amount": 1800}, # cost ₦1550
        {"qty": "4gb_monthly",   "type": "cg-data",  "label": "9Mobile 4GB - 30 days",   "amount": 2350}, # cost ₦2050
        {"qty": "5gb_monthly",   "type": "cg-data",  "label": "9Mobile 5GB - 30 days",   "amount": 2800}, # cost ₦2500
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

# =========================
# JAP SMM SERVICES
# These are website traffic services available on your JAP account.
# Rate is your selling price in Naira per 1000 visits.
# JAP cost is ~$0.175/1000 = ~₦280 at ₦1600/USD, so ₦600+ gives good margin.
# =========================

SMM_SERVICES = {
    "usa_traffic": [
        {"id": "1416", "label": "🇺🇸 USA Traffic from Google",    "min": 88, "max": 88888888, "amount": 600},
        {"id": "1417", "label": "🇺🇸 USA Traffic from Facebook",  "min": 88, "max": 88888888, "amount": 600},
        {"id": "1418", "label": "🇺🇸 USA Traffic from Instagram", "min": 88, "max": 88888888, "amount": 600},
        {"id": "1424", "label": "🇺🇸 USA Traffic from YouTube",   "min": 88, "max": 88888888, "amount": 600},
        {"id": "1422", "label": "🇺🇸 USA Traffic from Twitter",   "min": 88, "max": 88888888, "amount": 600},
        {"id": "1423", "label": "🇺🇸 USA Traffic from Reddit",    "min": 88, "max": 88888888, "amount": 600},
        {"id": "1419", "label": "🇺🇸 USA Traffic from Quora",     "min": 88, "max": 88888888, "amount": 600},
        {"id": "1421", "label": "🇺🇸 USA Traffic from Pinterest", "min": 88, "max": 88888888, "amount": 600},
        {"id": "1434", "label": "🇺🇸 USA Traffic from Fiverr",    "min": 88, "max": 88888888, "amount": 600},
        {"id": "1428", "label": "🇺🇸 USA Traffic from Wikipedia", "min": 88, "max": 88888888, "amount": 600},
    ],
    "uk_traffic": [
        {"id": "1441", "label": "🇬🇧 UK Traffic from Google",    "min": 88, "max": 88888888, "amount": 650},
        {"id": "1450", "label": "🇬🇧 UK Traffic from Facebook",  "min": 88, "max": 88888888, "amount": 650},
        {"id": "1451", "label": "🇬🇧 UK Traffic from Instagram", "min": 88, "max": 88888888, "amount": 650},
        {"id": "1449", "label": "🇬🇧 UK Traffic from YouTube",   "min": 88, "max": 88888888, "amount": 650},
        {"id": "1448", "label": "🇬🇧 UK Traffic from Reddit",    "min": 88, "max": 88888888, "amount": 650},
        {"id": "1460", "label": "🇬🇧 UK Traffic from Fiverr",    "min": 88, "max": 88888888, "amount": 650},
        {"id": "1461", "label": "🇬🇧 UK Traffic from Wikipedia", "min": 88, "max": 88888888, "amount": 650},
    ],
    "india_traffic": [
        {"id": "1463", "label": "🇮🇳 India Traffic from Google",    "min": 88, "max": 88888888, "amount": 500},
        {"id": "1471", "label": "🇮🇳 India Traffic from Facebook",  "min": 88, "max": 88888888, "amount": 500},
        {"id": "1472", "label": "🇮🇳 India Traffic from Instagram", "min": 88, "max": 88888888, "amount": 500},
        {"id": "1469", "label": "🇮🇳 India Traffic from YouTube",   "min": 88, "max": 88888888, "amount": 500},
        {"id": "1467", "label": "🇮🇳 India Traffic from Twitter",   "min": 88, "max": 88888888, "amount": 500},
        {"id": "1468", "label": "🇮🇳 India Traffic from Reddit",    "min": 88, "max": 88888888, "amount": 500},
        {"id": "1464", "label": "🇮🇳 India Traffic from Quora",     "min": 88, "max": 88888888, "amount": 500},
    ],
    "global_traffic": [
        {"id": "1498", "label": "🇩🇪 Germany Traffic from Google",  "min": 88,  "max": 88888888, "amount": 650},
        {"id": "1509", "label": "🇫🇷 France Traffic from Google",   "min": 100, "max": 1000000,  "amount": 650},
        {"id": "1521", "label": "🇨🇦 Canada Traffic from Google",   "min": 500, "max": 1000000,  "amount": 800},
        {"id": "1604", "label": "🇮🇹 Italy Traffic from Google",    "min": 500, "max": 1000000,  "amount": 800},
        {"id": "1607", "label": "🇪🇸 Spain Traffic from Google",    "min": 500, "max": 1000000,  "amount": 700},
        {"id": "1544", "label": "🇷🇺 Russia Traffic from Google",   "min": 500, "max": 1000000,  "amount": 700},
        {"id": "1474", "label": "🇧🇷 Brazil Traffic from Google",   "min": 88,  "max": 88888888, "amount": 600},
        {"id": "1624", "label": "🇯🇵 Japan Traffic from Google",    "min": 500, "max": 1000000,  "amount": 800},
        {"id": "1616", "label": "🇸🇬 Singapore Traffic from Google","min": 500, "max": 1000000,  "amount": 800},
        {"id": "1608", "label": "🇹🇷 Turkey Traffic from Google",   "min": 500, "max": 1000000,  "amount": 600},
    ],
}

#landing ######
def landing_page(request):
    return render(request, "landing.html")  
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
# BEEWAVE API  ← FIXED
# =========================

# ----------------------------------------------------------------
# HOW TO FIND YOUR CORRECT FIELD NAMES:
#   1. Log in to your Beewave dashboard
#   2. Go to API / Developer docs section
#   3. Confirm the exact values for:
#        - endpoint URL  (currently: https://beewave.ng/api/data.php)
#        - "type" field  (try: "SME", "sme", "data", "bundle")
#        - phone field   (try: "phone" or "phone_number")
#        - plan field    (try: "plan", "plan_id", "qty", "bundle_id")
#        - plan value    (try: "1" for 1GB, "500" for 500MB, or "1gb"/"500mb")
#
# The current values below are the most common for Nigerian VTU APIs.
# Check your terminal logs — the raw Beewave response is now printed.
# ----------------------------------------------------------------

# Map qty labels to plain numeric strings Beewave likely expects.
# e.g. "1gb" → "1",  "500mb" → "500mb"  (adjust if your dashboard says otherwise)
BEEWAVE_QTY_MAP = {
    "500mb": "500mb",
    "1gb":   "1gb",
    "2gb":   "2gb",
    "3gb":   "3gb",
    "5gb":   "5gb",
    "10gb":  "10gb",
}


import platform as _platform
import subprocess as _subprocess

# Windows dev: curl uses Schannel TLS which Beewave accepts.
# Linux prod:  httpx works fine — no WAF block on Linux OpenSSL.
_IS_WINDOWS = _platform.system() == "Windows"
logger.info(f"Beewave backend: {'curl (Windows)' if _IS_WINDOWS else 'httpx (Linux)'}")


def _beewave_via_curl(payload):
    """Windows only — call Beewave using system curl (Schannel TLS, bypasses WAF block)."""
    try:
        result = _subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "https://beewave.ng/api/data.php",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload),
                "--max-time", "30",
            ],
            capture_output=True, text=True, timeout=35,
        )
        raw = result.stdout.strip()
        if not raw:
            logger.error(f"Beewave curl no output. stderr: {result.stderr.strip()}")
            return None, "No response from Beewave."
        logger.info(f"Beewave curl raw: {raw}")
        return json.loads(raw), None
    except _subprocess.TimeoutExpired:
        return None, "Beewave request timed out."
    except json.JSONDecodeError as e:
        logger.error(f"Beewave curl JSON error: {e}")
        return None, "Beewave returned unexpected response."
    except FileNotFoundError:
        return None, "curl not found on this system."
    except Exception as e:
        logger.error(f"Beewave curl error: {e}")
        return None, "Network error contacting Beewave."


def _beewave_via_httpx(payload):
    """Linux/production — call Beewave using httpx HTTP/1.1."""
    import httpx
    try:
        with httpx.Client(http2=False, timeout=30) as client:
            response = client.post(
                "https://beewave.ng/api/data.php",
                json=payload,
            )
        logger.info(f"Beewave HTTP {response.status_code} | raw: {response.text[:500]}")
        if response.status_code != 200:
            return None, f"Beewave server error (HTTP {response.status_code})"
        try:
            return response.json(), None
        except ValueError:
            logger.error(f"Beewave non-JSON: {response.text[:300]}")
            return None, "Beewave returned unexpected response format."
    except httpx.ConnectError as e:
        logger.error(f"Beewave connect error: {e}")
        return None, "Could not connect to Beewave. Please try again."
    except httpx.TimeoutException:
        return None, "Beewave request timed out. Please try again."
    except Exception as e:
        logger.error(f"Beewave unexpected error: {e}")
        return None, "Network error contacting Beewave."


def call_beewave_data_api(network, phone, qty, plan_type="sme-data"):
    """
    Call Beewave data API.
    Returns (True, reference) on success, (False, error_message) on failure.
    Windows → curl subprocess (Schannel TLS, bypasses WAF).
    Linux   → httpx (no WAF issue on Linux OpenSSL).
    plan_type varies per network: sme-data (MTN), cg-data (GLO/9Mobile),
    direct-gifting-data (Airtel).
    """
    api_key      = config("BEEWAVE_API_KEY")
    network_name = BEEWAVE_NETWORK_NAMES.get(network)

    if not network_name:
        return False, f"Unknown network: {network}"

    payload = {
        "api_key":      api_key,
        "type":         plan_type,    # sme-data / cg-data / direct-gifting-data
        "qty":          qty,          # exact code e.g. "1gb_weekly", "500mb_monthly"
        "network":      network_name, # lowercase: "mtn", "glo", "airtel", "9mobile"
        "phone_number": phone,        # exact field name per Beewave docs
    }

    logger.info(f"Beewave → network={network_name} plan={plan_value} phone={phone} via={'curl' if _IS_WINDOWS else 'httpx'}")

    if _IS_WINDOWS:
        data, err = _beewave_via_curl(payload)
    else:
        data, err = _beewave_via_httpx(payload)

    if err:
        return False, err

    logger.info(f"Beewave parsed: {data}")
    status = data.get("status", "")

    if status == "success":
        return True, data.get("reference", "beewave-ok")
    elif status == "pending":
        return True, data.get("reference", "pending")
    else:
        error_msg = data.get("desc", data.get("message", "Transaction failed"))
        logger.error(f"Beewave error response: {data}")
        return False, error_msg


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

        # ── Customer account ──────────────────────────────────────────
        try:
            customer_account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if customer_account.balance < amount:
            return redirect("low_balance")

        # ── Owner account (funds the API call) ────────────────────────
        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_data: owner account error: {e}")
            messages.error(request, "Service temporarily unavailable. Please try again later.")
            return redirect("buy_data")

        request_id   = str(uuid.uuid4()).replace("-", "")[:20]
        is_owner_buying = (customer_account.pk == owner_account.pk)

        # Only transfer to owner if buyer is a different user (real customer)
        with db_transaction.atomic():
            customer_account.balance -= amount
            customer_account.save()
            if not is_owner_buying:
                owner_account.balance += amount
                owner_account.save()

        try:
            success_flag, ck_response = call_clubkonnect_data_api(
                network, phone, plan_id, request_id
            )
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()
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
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()

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
        qty     = request.POST.get("qty", "").strip()

        if not network or not phone or not qty:
            messages.error(request, "Network, phone number, and data plan are required.")
            return redirect("payment")

        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number.")
            return redirect("payment")

        network_plans = BEEWAVE_PLANS.get(network, [])
        plan_info     = next((p for p in network_plans if p["qty"] == qty), None)

        if not plan_info:
            messages.error(request, "Invalid data plan selected.")
            return redirect("payment")

        amount     = Decimal(str(plan_info["amount"]))
        plan_type  = plan_info.get("type", "sme-data")  # type per plan e.g. sme-data, cg-data

        # ── Customer account ──────────────────────────────────────────
        try:
            customer_account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if customer_account.balance < amount:
            return redirect("low_balance")

        # ── Owner account (funds the Beewave API call) ─────────────────
        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_special_bundle: owner account error: {e}")
            messages.error(request, "Service temporarily unavailable. Please try again later.")
            return redirect("payment")

        is_owner_buying = (customer_account.pk == owner_account.pk)

        with db_transaction.atomic():
            customer_account.balance -= amount
            customer_account.save()
            if not is_owner_buying:
                owner_account.balance += amount
                owner_account.save()

        try:
            success_flag, bw_response = call_beewave_data_api(network, phone, qty, plan_type)
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()
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
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()

            bw_lower = bw_response.lower()
            if "insufficient" in bw_lower:
                error_msg = "Our data provider balance is low. Please try again later."
            elif "invalid" in bw_lower:
                error_msg = "Invalid request. Please check your details and try again."
            elif "timed out" in bw_lower:
                error_msg = "Request timed out. Please try again in a moment."
            elif "connect" in bw_lower:
                error_msg = "Could not reach data provider. Please try again shortly."
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
        "platform_labels": {
            "usa_traffic":    "🇺🇸 USA Traffic",
            "uk_traffic":     "🇬🇧 UK Traffic",
            "india_traffic":  "🇮🇳 India Traffic",
            "global_traffic": "🌍 Global Traffic",
        },
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

        # SMM uses account directly — no owner transfer needed for traffic services
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


# =========================
# FOREIGN NUMBERS — 5SIM
# =========================

FOREIGN_COUNTRIES = ["usa", "uk", "canada", "russia", "india", "indonesia"]
FOREIGN_SERVICES  = ["telegram", "whatsapp", "google", "facebook", "instagram", "twitter"]


def _ngn_price(usd_price):
    """
    Convert a USD price to NGN with your profit markup applied.
    Reads from .env:
      USD_TO_NGN_RATE       — exchange rate e.g. 1600
      FOREIGN_NUMBER_MARKUP — profit multiplier e.g. 1.3 = 30% markup
    Result is rounded up to the nearest 10 naira for clean pricing.
    """
    import math
    # Strip spaces, quotes, inline comments — handles messy .env values
    def clean(val):
        return str(val).split("#")[0].strip().strip('"').strip("'")

    try:
        rate   = Decimal(clean(config("USD_TO_NGN_RATE",        default="1600")))
        markup = Decimal(clean(config("FOREIGN_NUMBER_MARKUP",   default="1.3")))
    except Exception as e:
        logger.error(f"_ngn_price config error: {e} — using defaults 1600 / 1.3")
        rate   = Decimal("1600")
        markup = Decimal("1.3")

    ngn = Decimal(str(usd_price)) * rate * markup
    return Decimal(str(math.ceil(float(ngn) / 10) * 10))


def _fetch_5sim_prices(country=None, service=None):
    """
    Fetch live prices from 5SIM and convert to NGN with markup.
    If country AND service are provided, returns only matching rows.
    Returns list of dicts: {country, service, operator, price_usd, price_ngn, count}
    price_ngn is what the customer pays (NGN, with your markup baked in).
    price_usd is the raw 5SIM cost (what actually gets charged to your 5SIM account).
    """
    try:
        response = requests.get("https://5sim.net/v1/guest/prices", timeout=30)
        data     = response.json()
    except Exception as e:
        logger.error(f"5SIM price fetch error: {e}")
        return []

    prices    = []
    countries = [country] if country else FOREIGN_COUNTRIES
    services  = [service]  if service  else FOREIGN_SERVICES

    for c in countries:
        if c not in data:
            continue
        for s in services:
            if s not in data[c]:
                continue
            for operator_name, operator_data in data[c][s].items():
                usd = operator_data.get("cost", 0)
                prices.append({
                    "country":   c,
                    "service":   s,
                    "operator":  operator_name,
                    "price_usd": usd,
                    "price_ngn": _ngn_price(usd),   # what customer pays in ₦
                    "price":     _ngn_price(usd),    # alias kept for template compatibility
                    "count":     operator_data.get("count", 0),
                })
    return prices


@login_required
def buy_foreign_number(request):
    """
    GET  → show form + user's numbers. Prices only load after country/service selected.
    POST → customer balance deducted, owner account credited, 5SIM API called with owner key.
           If API fails, customer is refunded and owner balance restored.
    """
    customer_account = get_or_create_account(request.user)

    selected_country = request.GET.get("country", "") or request.POST.get("country", "")
    selected_service = request.GET.get("service", "") or request.POST.get("service", "")

    prices = []
    if selected_country and selected_service:
        prices = _fetch_5sim_prices(
            country=selected_country if selected_country in FOREIGN_COUNTRIES else None,
            service=selected_service if selected_service in FOREIGN_SERVICES  else None,
        )

    if request.method == "POST":
        country = request.POST.get("country", "").strip().lower()
        service = request.POST.get("service", "").strip().lower()

        if not country or not service:
            messages.error(request, "Please select a country and service.")
            return redirect("buy_foreign_number")

        if country not in FOREIGN_COUNTRIES:
            messages.error(request, "Invalid country selected.")
            return redirect("buy_foreign_number")

        if service not in FOREIGN_SERVICES:
            messages.error(request, "Invalid service selected.")
            return redirect("buy_foreign_number")

        plan_prices = _fetch_5sim_prices(country=country, service=service)
        available   = [p for p in plan_prices if p["count"] > 0]

        if not available:
            messages.error(request, "No available numbers right now. Try another country or service.")
            return redirect(f"buy_foreign_number?country={country}&service={service}")

        cheapest       = min(available, key=lambda x: x["price_ngn"])
        selected_price = Decimal(str(cheapest["price_ngn"]))  # NGN with markup — what customer pays

        if customer_account.balance < selected_price:
            messages.error(request, f"Insufficient balance. You need ₦{selected_price:,} for this number.")
            return redirect("buy_foreign_number")

        # ── Owner account (the 5SIM API key belongs to the owner) ──────
        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_foreign_number: owner account error: {e}")
            messages.error(request, "Service temporarily unavailable. Please try again later.")
            return redirect("buy_foreign_number")

        # Deduct customer, credit owner — atomically
        is_owner_buying = (customer_account.pk == owner_account.pk)

        with db_transaction.atomic():
            customer_account.balance -= selected_price
            customer_account.save()
            if not is_owner_buying:
                owner_account.balance += selected_price
                owner_account.save()

        try:
            headers = {
                "Authorization": f"Bearer {settings.FIVE_SIM_API_KEY}",
                "Accept":        "application/json",
            }
            buy_url  = f"https://5sim.net/v1/user/buy/activation/{country}/any/{service}"
            response = requests.get(buy_url, headers=headers, timeout=30)

            logger.info(f"5SIM buy → HTTP {response.status_code} | {response.text[:300]}")

            if response.status_code == 200:
                data = response.json()
                ForeignNumber.objects.create(
                    user         = request.user,
                    order_id     = data.get("id"),
                    country      = data.get("country"),
                    service      = data.get("product"),
                    phone_number = data.get("phone"),
                    price        = selected_price,
                    status       = "PENDING",
                )
                messages.success(request, f"Number {data.get('phone')} purchased successfully!")

            else:
                # API failed — refund customer, restore owner
                with db_transaction.atomic():
                    customer_account.balance += selected_price
                    customer_account.save()
                    if not is_owner_buying:
                        owner_account.balance -= selected_price
                        owner_account.save()

                try:
                    err_data = response.json()
                    err_msg  = err_data.get("message") or err_data.get("error") or response.text
                except Exception:
                    err_msg = response.text

                err_lower = err_msg.lower()
                if "no free phones" in err_lower:
                    messages.error(request, "No available numbers right now. Try another country or service.")
                elif "not enough user balance" in err_lower:
                    messages.error(request, "5SIM provider balance is low. Contact support.")
                else:
                    messages.error(request, f"Purchase failed: {err_msg}")

        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += selected_price
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= selected_price
                    owner_account.save()
            logger.error(f"5SIM buy error: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")

        return redirect(f"/buy-foreign-number/?country={country}&service={service}")

    numbers = ForeignNumber.objects.filter(user=request.user).order_by("-created_at")

    context = {
        "account":          customer_account,
        "countries":        FOREIGN_COUNTRIES,
        "services":         FOREIGN_SERVICES,
        "numbers":          numbers,
        "prices":           prices,
        "selected_country": selected_country,
        "selected_service": selected_service,
    }
    return render(request, "buy_foreign_number.html", context)


@login_required
def foreign_number_prices(request):
    """AJAX endpoint — returns prices for a specific country+service as JSON."""
    country = request.GET.get("country", "").strip().lower()
    service = request.GET.get("service", "").strip().lower()

    if not country or not service:
        return JsonResponse({"prices": [], "error": "country and service required"})

    prices = _fetch_5sim_prices(
        country=country if country in FOREIGN_COUNTRIES else None,
        service=service if service  in FOREIGN_SERVICES  else None,
    )
    return JsonResponse({"prices": prices})


@login_required
def cancel_foreign_number(request, order_id):
    try:
        foreign_number = ForeignNumber.objects.get(order_id=order_id, user=request.user)
    except ForeignNumber.DoesNotExist:
        messages.error(request, "Number not found.")
        return redirect("buy_foreign_number")

    try:
        headers  = {
            "Authorization": f"Bearer {settings.FIVE_SIM_API_KEY}",
            "Accept":        "application/json",
        }
        response = requests.get(
            f"https://5sim.net/v1/user/cancel/{order_id}",
            headers=headers, timeout=30,
        )
        logger.info(f"5SIM cancel → HTTP {response.status_code} | {response.text[:200]}")

        if response.status_code == 200:
            foreign_number.status = "CANCELLED"
            foreign_number.save()
            messages.success(request, "Number cancelled successfully.")
        else:
            messages.error(request, "Unable to cancel number. It may have already expired.")

    except Exception as e:
        logger.error(f"5SIM cancel error: {e}")
        messages.error(request, str(e))

    return redirect("buy_foreign_number")


# =========================
# ELECTRICITY — CLUBKONNECT
# =========================

ELECTRIC_COMPANIES = {
    "01": "Eko Electric (EKEDC)",
    "02": "Ikeja Electric (IKEDC)",
    "03": "Abuja Electric (AEDC)",
    "04": "Kano Electric (KEDC)",
    "05": "Portharcourt Electric (PHEDC)",
    "06": "Jos Electric (JEDC)",
    "07": "Ibadan Electric (IBEDC)",
    "08": "Kaduna Electric (KAEDC)",
    "09": "Enugu Electric (EEDC)",
    "10": "Benin Electric (BEDC)",
    "11": "Yola Electric (YEDC)",
    "12": "Aba Electric (APLE)",
}

METER_TYPES = {
    "01": "Prepaid",
    "02": "Postpaid",
}


def verify_meter(electric_company, meter_no, meter_type):
    """Verify a meter number via ClubKonnect before purchase."""
    user_id = config("CLUBKONNECT_USER_ID")
    api_key = config("CLUBKONNECT_API_KEY")
    url = (
        f"https://www.nellobytesystems.com/APIVerifyElectricityV1.asp"
        f"?UserID={user_id}&APIKey={api_key}"
        f"&ElectricCompany={electric_company}&MeterNo={meter_no}&MeterType={meter_type}"
    )
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        name = data.get("customer_name", "")
        if name and name != "INVALID_METERNO":
            return True, name
        return False, "Invalid meter number"
    except Exception as e:
        logger.error(f"Meter verify error: {e}")
        return False, "Could not verify meter number"


def call_clubkonnect_electricity_api(electric_company, meter_type, meter_no, amount, phone, request_id):
    user_id  = config("CLUBKONNECT_USER_ID")
    api_key  = config("CLUBKONNECT_API_KEY")
    site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
    url = (
        f"https://www.nellobytesystems.com/APIElectricityV1.asp"
        f"?UserID={user_id}&APIKey={api_key}"
        f"&ElectricCompany={electric_company}&MeterType={meter_type}"
        f"&MeterNo={meter_no}&Amount={amount}&PhoneNo={phone}"
        f"&RequestID={request_id}&CallBackURL={site_url}/webhook/clubkonnect/"
    )
    logger.info(f"ClubKonnect Electricity → company={electric_company} meter={meter_no} amount={amount}")
    try:
        resp = requests.get(url, timeout=15)
        text = resp.text.strip()
        logger.info(f"ClubKonnect Electricity response: {text}")
        try:
            data        = json.loads(text)
            status      = data.get("status", "")
            status_code = str(data.get("statuscode", ""))
            if status == "ORDER_RECEIVED" or status_code == "100":
                return True, data.get("metertoken", ""), data.get("orderid", "")
            elif status == "INSUFFICIENT_BALANCE":
                return False, "insufficient balance in provider wallet", ""
            elif status in ("INVALID_CREDENTIALS", "INVALID_APIKEY"):
                return False, "invalid api credentials", ""
            elif status == "INVALID_MeterNo":
                return False, "invalid meter number", ""
            else:
                logger.error(f"ClubKonnect Electricity error: {text}")
                return False, text, ""
        except json.JSONDecodeError:
            logger.error(f"ClubKonnect Electricity non-JSON: {text}")
            return False, text, ""
    except requests.RequestException as e:
        logger.error(f"ClubKonnect Electricity request failed: {e}")
        return False, "Network error contacting ClubKonnect.", ""


@login_required
def buy_electricity(request):
    account = get_or_create_account(request.user)

    # AJAX meter verification
    if request.method == "GET" and request.GET.get("verify_meter"):
        company    = request.GET.get("company", "")
        meter_no   = request.GET.get("meter_no", "")
        meter_type = request.GET.get("meter_type", "01")
        ok, result = verify_meter(company, meter_no, meter_type)
        return JsonResponse({"success": ok, "customer_name": result if ok else "", "error": result if not ok else ""})

    if request.method == "POST":
        company    = request.POST.get("electric_company", "").strip()
        meter_type = request.POST.get("meter_type", "01").strip()
        meter_no   = request.POST.get("meter_no", "").strip()
        phone      = request.POST.get("phone", "").strip()
        amount_raw = request.POST.get("amount", "").strip()

        if not all([company, meter_type, meter_no, phone, amount_raw]):
            messages.error(request, "All fields are required.")
            return redirect("buy_electricity")

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("buy_electricity")

        if amount < 1000:
            messages.error(request, "Minimum electricity purchase is ₦1,000.")
            return redirect("buy_electricity")

        if company not in ELECTRIC_COMPANIES:
            messages.error(request, "Invalid electricity company selected.")
            return redirect("buy_electricity")

        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number.")
            return redirect("buy_electricity")

        try:
            customer_account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if customer_account.balance < amount:
            return redirect("low_balance")

        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_electricity: owner account error: {e}")
            messages.error(request, "Service temporarily unavailable.")
            return redirect("buy_electricity")

        request_id = str(uuid.uuid4()).replace("-", "")[:20]

        is_owner_buying = (customer_account.pk == owner_account.pk)

        with db_transaction.atomic():
            customer_account.balance -= amount
            customer_account.save()
            if not is_owner_buying:
                owner_account.balance += amount
                owner_account.save()

        try:
            success_flag, token, order_id = call_clubkonnect_electricity_api(
                company, meter_type, meter_no, int(amount), phone, request_id
            )
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                owner_account.balance -= amount
                owner_account.save()
            logger.error(f"buy_electricity crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("buy_electricity")

        company_name = ELECTRIC_COMPANIES.get(company, company)
        meter_label  = METER_TYPES.get(meter_type, meter_type)

        if success_flag:
            ElectricityPurchase.objects.create(
                user             = request.user,
                electric_provider = company_name,   # existing column
                meter_type       = meter_label,
                meter_number     = meter_no,        # existing column name
                amount           = amount,
                token            = token,
                reference        = request_id,
                status           = "successful",
            )
            messages.success(request, f"₦{amount:,} electricity purchased! Token: {token}")
            return redirect("buy_electricity")
        else:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()

            if "insufficient" in success_flag if isinstance(success_flag, str) else "insufficient" in str(token).lower():
                error_msg = "Provider balance is low. Please try again later."
            else:
                error_msg = f"Purchase failed: {token}. Your balance has been refunded."

            messages.error(request, error_msg)
            return redirect("buy_electricity")

    purchases = ElectricityPurchase.objects.filter(user=request.user).order_by("-created_at")[:10]
    context = {
        "account":     account,
        "companies":   ELECTRIC_COMPANIES,
        "meter_types": METER_TYPES,
        "purchases":   purchases,
    }
    return render(request, "buy_electricity.html", context)


# =========================
# CABLE TV — CLUBKONNECT
# =========================

CABLE_TV_PROVIDERS = {
    "dstv":      "DStv",
    "gotv":      "GOtv",
    "startimes": "StarTimes",
    "showmax":   "Showmax",
}

CABLE_TV_PACKAGES = {
    "dstv": [
        {"code": "dstv-padi",              "label": "DStv Padi",                    "amount": 4600},
        {"code": "dstv-yanga",             "label": "DStv Yanga",                   "amount": 6200},
        {"code": "dstv-confam",            "label": "DStv Confam",                  "amount": 11400},
        {"code": "dstv79",                 "label": "DStv Compact",                 "amount": 19500},
        {"code": "dstv7",                  "label": "DStv Compact Plus",            "amount": 30500},
        {"code": "dstv3",                  "label": "DStv Premium",                 "amount": 45000},
        {"code": "confam-extra",           "label": "DStv Confam + ExtraView",      "amount": 17000},
        {"code": "yanga-extra",            "label": "DStv Yanga + ExtraView",       "amount": 12000},
        {"code": "padi-extra",             "label": "DStv Padi + ExtraView",        "amount": 10400},
        {"code": "dstv30",                 "label": "DStv Compact + ExtraView",     "amount": 25000},
        {"code": "dstv33",                 "label": "DStv Premium + ExtraView",     "amount": 50500},
        {"code": "dstv45",                 "label": "DStv Compact Plus + ExtraView","amount": 36000},
    ],
    "gotv": [
        {"code": "gotv-smallie",  "label": "GOtv Smallie",  "amount": 2200},
        {"code": "gotv-jinja",    "label": "GOtv Jinja",    "amount": 4200},
        {"code": "gotv-jolli",    "label": "GOtv Jolli",    "amount": 6100},
        {"code": "gotv-max",      "label": "GOtv Max",      "amount": 8700},
        {"code": "gotv-super",    "label": "GOtv Super",    "amount": 11700},
    ],
    "startimes": [
        {"code": "nova_weekly",    "label": "StarTimes Nova Weekly",    "amount": 900},
        {"code": "basic_weekly",   "label": "StarTimes Basic Weekly",   "amount": 1600},
        {"code": "classic_weekly", "label": "StarTimes Classic Weekly", "amount": 2200},
        {"code": "smart_weekly",   "label": "StarTimes Smart Weekly",   "amount": 1900},
        {"code": "super_weekly",   "label": "StarTimes Super Weekly",   "amount": 3400},
        {"code": "nova",           "label": "StarTimes Nova Monthly",   "amount": 2300},
        {"code": "basic",          "label": "StarTimes Basic Monthly",  "amount": 4200},
        {"code": "classic",        "label": "StarTimes Classic Monthly","amount": 6200},
        {"code": "smart",          "label": "StarTimes Smart Monthly",  "amount": 5300},
        {"code": "super",          "label": "StarTimes Super Monthly",  "amount": 9700},
    ],
    "showmax": [
        {"code": "showmax",        "label": "Showmax Mobile",           "amount": 2900},
        {"code": "showmax-premier-league", "label": "Showmax Premier League", "amount": 3600},
    ],
}


def verify_smartcard(cable_tv, smartcard_no):
    """Verify a smartcard/IUC number before purchase."""
    user_id = config("CLUBKONNECT_USER_ID")
    api_key = config("CLUBKONNECT_API_KEY")
    url = (
        f"https://www.nellobytesystems.com/APIVerifyCableTVV1.asp"
        f"?UserID={user_id}&APIKey={api_key}"
        f"&CableTV={cable_tv}&SmartCardNo={smartcard_no}"
    )
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        name = data.get("customer_name", "")
        if name and name != "INVALID_SMARTCARDNO":
            return True, name
        return False, "Invalid smartcard number"
    except Exception as e:
        logger.error(f"Smartcard verify error: {e}")
        return False, "Could not verify smartcard"


def call_clubkonnect_cabletv_api(cable_tv, package, smartcard_no, phone, request_id):
    user_id  = config("CLUBKONNECT_USER_ID")
    api_key  = config("CLUBKONNECT_API_KEY")
    site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
    url = (
        f"https://www.nellobytesystems.com/APICableTVV1.asp"
        f"?UserID={user_id}&APIKey={api_key}"
        f"&CableTV={cable_tv}&Package={package}"
        f"&SmartCardNo={smartcard_no}&PhoneNo={phone}"
        f"&RequestID={request_id}&CallBackURL={site_url}/webhook/clubkonnect/"
    )
    logger.info(f"ClubKonnect CableTV → tv={cable_tv} pkg={package} card={smartcard_no}")
    try:
        resp = requests.get(url, timeout=15)
        text = resp.text.strip()
        logger.info(f"ClubKonnect CableTV response: {text}")
        try:
            data        = json.loads(text)
            status      = data.get("status", "")
            status_code = str(data.get("statuscode", ""))
            if status == "ORDER_RECEIVED" or status_code == "100":
                return True, data.get("orderid", request_id)
            elif status == "INSUFFICIENT_BALANCE":
                return False, "insufficient balance in provider wallet"
            elif status in ("INVALID_CREDENTIALS", "INVALID_APIKEY"):
                return False, "invalid api credentials"
            elif status == "INVALID_SMARTCARDNO":
                return False, "invalid smartcard number"
            elif status == "PACKAGE_NOT_AVAILABLE":
                return False, "selected package is not available"
            else:
                logger.error(f"ClubKonnect CableTV error: {text}")
                return False, text
        except json.JSONDecodeError:
            logger.error(f"ClubKonnect CableTV non-JSON: {text}")
            return False, text
    except requests.RequestException as e:
        logger.error(f"ClubKonnect CableTV request failed: {e}")
        return False, "Network error contacting ClubKonnect."


@login_required
def buy_cable_tv(request):
    account = get_or_create_account(request.user)

    # AJAX smartcard verification
    if request.method == "GET" and request.GET.get("verify_card"):
        cable_tv     = request.GET.get("cable_tv", "")
        smartcard_no = request.GET.get("smartcard_no", "")
        ok, result   = verify_smartcard(cable_tv, smartcard_no)
        return JsonResponse({"success": ok, "customer_name": result if ok else "", "error": result if not ok else ""})

    # AJAX package list for selected provider
    if request.method == "GET" and request.GET.get("get_packages"):
        cable_tv = request.GET.get("cable_tv", "")
        packages = CABLE_TV_PACKAGES.get(cable_tv, [])
        return JsonResponse({"packages": packages})

    if request.method == "POST":
        cable_tv     = request.POST.get("cable_tv", "").strip().lower()
        package_code = request.POST.get("package", "").strip()
        smartcard_no = request.POST.get("smartcard_no", "").strip()
        phone        = request.POST.get("phone", "").strip()

        if not all([cable_tv, package_code, smartcard_no, phone]):
            messages.error(request, "All fields are required.")
            return redirect("buy_cable_tv")

        if cable_tv not in CABLE_TV_PROVIDERS:
            messages.error(request, "Invalid cable TV provider.")
            return redirect("buy_cable_tv")

        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number.")
            return redirect("buy_cable_tv")

        packages    = CABLE_TV_PACKAGES.get(cable_tv, [])
        package_info = next((p for p in packages if p["code"] == package_code), None)

        if not package_info:
            messages.error(request, "Invalid package selected.")
            return redirect("buy_cable_tv")

        amount = Decimal(str(package_info["amount"]))

        try:
            customer_account = Account.objects.get(user=request.user)
        except Account.DoesNotExist:
            messages.error(request, "Wallet account not found.")
            return redirect("home")

        if customer_account.balance < amount:
            return redirect("low_balance")

        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_cable_tv: owner account error: {e}")
            messages.error(request, "Service temporarily unavailable.")
            return redirect("buy_cable_tv")

        request_id = str(uuid.uuid4()).replace("-", "")[:20]

        is_owner_buying = (customer_account.pk == owner_account.pk)

        with db_transaction.atomic():
            customer_account.balance -= amount
            customer_account.save()
            if not is_owner_buying:
                owner_account.balance += amount
                owner_account.save()

        try:
            success_flag, ck_response = call_clubkonnect_cabletv_api(
                cable_tv, package_code, smartcard_no, phone, request_id
            )
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                owner_account.balance -= amount
                owner_account.save()
            logger.error(f"buy_cable_tv crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("buy_cable_tv")

        provider_name = CABLE_TV_PROVIDERS.get(cable_tv, cable_tv)

        if success_flag:
            CableTVPurchase.objects.create(
                user          = request.user,
                provider      = cable_tv,
                provider_name = provider_name,
                package_code  = package_code,
                package_name  = package_info["label"],
                smartcard_no  = smartcard_no,
                phone         = phone,
                amount        = amount,
                order_id      = ck_response,
                reference     = request_id,
                status        = "successful",
            )
            messages.success(request, f"{package_info['label']} subscription successful for {smartcard_no}!")
            return redirect("buy_cable_tv")
        else:
            with db_transaction.atomic():
                customer_account.balance += amount
                customer_account.save()
                if not is_owner_buying:
                    owner_account.balance -= amount
                    owner_account.save()

            ck_lower = ck_response.lower()
            if "insufficient" in ck_lower:
                error_msg = "Provider balance is low. Please try again later."
            elif "invalid smartcard" in ck_lower:
                error_msg = "Invalid smartcard number. Please check and try again."
            elif "not available" in ck_lower:
                error_msg = "Selected package is currently unavailable."
            else:
                error_msg = f"Subscription failed: {ck_response}. Your balance has been refunded."

            messages.error(request, error_msg)
            return redirect("buy_cable_tv")

    purchases = CableTVPurchase.objects.filter(user=request.user).order_by("-created_at")[:10]
    context = {
        "account":   account,
        "providers": CABLE_TV_PROVIDERS,
        "packages":  json.dumps(CABLE_TV_PACKAGES),
        "purchases": purchases,
    }
    return render(request, "buy_cable_tv.html", context)