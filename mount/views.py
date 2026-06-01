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


def _deduct_from_owner(owner_account, amount):
    """Safely deduct amount from owner inside an existing atomic block."""
    try:
        owner = Account.objects.select_for_update().get(pk=owner_account.pk)
        owner.balance -= amount
        owner.save()
    except Exception as e:
        logger.error(f"Owner balance deduct failed: {e}")


# =========================
# AUTH VIEWS
# =========================
def signup(request):
    if request.method == "POST":
        username         = request.POST.get("username", "").strip()
        full_name        = request.POST.get("full_name", "").strip()
        email            = request.POST.get("email", "").strip()
        phone            = request.POST.get("phone", "").strip()
        password         = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect("signup")
        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("signup")
        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return redirect("signup")
        if User.objects.filter(username=username).exists():
            messages.error(request, "That username is already taken.")
            return redirect("signup")
        if email and User.objects.filter(email=email).exists():
            messages.error(request, "An account with that email already exists.")
            return redirect("signup")

        name_parts = full_name.split(" ", 1)
        first_name = name_parts[0]
        last_name  = name_parts[1] if len(name_parts) > 1 else ""

        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name,
        )

        try:
            detail, _ = Detail.objects.get_or_create(user=user)
            if phone:
                detail.phone_number = phone  # ← correct field name
                detail.save()
        except Exception as e:
            logger.error(f"Signup Detail save error: {e}")

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
# DATA PLANS & NETWORK CONSTANTS
# =========================

NETWORK_CODES = {"MTN": "01", "GLO": "02", "AIRTEL": "04", "9MOBILE": "03"}

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

BEEWAVE_PLANS = {
    "MTN": [
        {"qty": "500mb_weekly",  "type": "sme-data", "label": "MTN 500MB - 7 days",   "amount": 390},
        {"qty": "1gb_weekly",    "type": "sme-data", "label": "MTN 1GB - 7 days",     "amount": 530},
        {"qty": "2gb_weekly",    "type": "sme-data", "label": "MTN 2GB - 7 days",     "amount": 980},
        {"qty": "3gb_weekly",    "type": "sme-data", "label": "MTN 3GB - 7 days",     "amount": 1350},
        {"qty": "1gb_monthly",   "type": "sme-data", "label": "MTN 1GB - 30 days",    "amount": 650},
        {"qty": "2gb_monthly",   "type": "sme-data", "label": "MTN 2GB - 30 days",    "amount": 1150},
        {"qty": "3gb_monthly",   "type": "sme-data", "label": "MTN 3GB - 30 days",    "amount": 1700},
        {"qty": "5gb_monthly",   "type": "sme-data", "label": "MTN 5GB - 30 days",    "amount": 2050},
    ],
    "GLO": [
        {"qty": "200mb_weekly",  "type": "cg-data",  "label": "GLO 200MB - 7 days",   "amount": 140},
        {"qty": "1gb_3days",     "type": "cg-data",  "label": "GLO 1GB - 3 days",     "amount": 330},
        {"qty": "1gb_7days",     "type": "cg-data",  "label": "GLO 1GB - 7 days",     "amount": 380},
        {"qty": "3gb_3days",     "type": "cg-data",  "label": "GLO 3GB - 3 days",     "amount": 950},
        {"qty": "3gb_7days",     "type": "cg-data",  "label": "GLO 3GB - 7 days",     "amount": 1100},
        {"qty": "500mb_monthly", "type": "cg-data",  "label": "GLO 500MB - 30 days",  "amount": 280},
        {"qty": "1gb_monthly",   "type": "cg-data",  "label": "GLO 1GB - 30 days",    "amount": 520},
        {"qty": "2gb_monthly",   "type": "cg-data",  "label": "GLO 2GB - 30 days",    "amount": 990},
        {"qty": "5gb_monthly",   "type": "cg-data",  "label": "GLO 5GB - 30 days",    "amount": 2400},
    ],
    "AIRTEL": [
        {"qty": "150mb_daily",   "type": "direct-gifting-data", "label": "Airtel 150MB - 1 day",   "amount": 100},
        {"qty": "300mb_2days",   "type": "direct-gifting-data", "label": "Airtel 300MB - 2 days",  "amount": 150},
        {"qty": "600mb_2days",   "type": "direct-gifting-data", "label": "Airtel 600MB - 2 days",  "amount": 270},
        {"qty": "1.5gb_1days",   "type": "direct-gifting-data", "label": "Airtel 1.5GB - 1 day",   "amount": 550},
        {"qty": "2gb_2days",     "type": "direct-gifting-data", "label": "Airtel 2GB - 2 days",    "amount": 650},
        {"qty": "3gb_2days",     "type": "direct-gifting-data", "label": "Airtel 3GB - 2 days",    "amount": 900},
        {"qty": "10gb_monthly",  "type": "direct-gifting-data", "label": "Airtel 10GB - 30 days",  "amount": 3500},
    ],
    "9MOBILE": [
        {"qty": "500mb_weekly",  "type": "cg-data",  "label": "9Mobile 500MB - 7 days",  "amount": 360},
        {"qty": "1gb_monthly",   "type": "cg-data",  "label": "9Mobile 1GB - 30 days",   "amount": 650},
        {"qty": "1.5gb_monthly", "type": "cg-data",  "label": "9Mobile 1.5GB - 30 days", "amount": 950},
        {"qty": "3gb_monthly",   "type": "cg-data",  "label": "9Mobile 3GB - 30 days",   "amount": 1800},
        {"qty": "4gb_monthly",   "type": "cg-data",  "label": "9Mobile 4GB - 30 days",   "amount": 2350},
        {"qty": "5gb_monthly",   "type": "cg-data",  "label": "9Mobile 5GB - 30 days",   "amount": 2800},
    ],
}

BEEWAVE_NETWORK_NAMES = {"MTN": "mtn", "GLO": "glo", "AIRTEL": "airtel", "9MOBILE": "9mobile"}

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


# =========================
# PAGE VIEWS
# =========================

def landing_page(request):
    return render(request, "landing.html")


@login_required
def home(request):
    account             = get_or_create_account(request.user)
    recent_transactions = Transaction.objects.filter(user=request.user).order_by("-created_at")[:5]
    context = {
        "account":             account,
        "recent_transactions": recent_transactions,
        "total_deposits":    Transaction.objects.filter(user=request.user, transaction_type="deposit",  status="successful").count(),
        "total_withdrawals": Transaction.objects.filter(user=request.user, transaction_type="withdraw", status="successful").count(),
        "total_data":        DataPurchase.objects.filter(user=request.user, status="successful").count(),
        "total_smm":         SMMOrder.objects.filter(user=request.user, status="completed").count(),
    }
    return render(request, "home.html", context)


@login_required
def payment(request):
    account      = get_or_create_account(request.user)
    transactions = Transaction.objects.filter(user=request.user).order_by("-created_at")[:10]
    detail, _    = Detail.objects.get_or_create(user=request.user)
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
    return render(request, "report.html", {"transactions": transactions, "data_purchases": data_purchases, "smm_orders": smm_orders})


@login_required
def success(request):      return render(request, "success.html")
@login_required
def succed_data(request):  return render(request, "succed_data.html")
@login_required
def succed_trans(request): return render(request, "succed_trans.html")
def low_balance(request):  return render(request, "low_balance.html")
def transfer(request):     return render(request, "transfer.html")


# =========================
# API VIEWS
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


@api_view(["POST"])
def api_login(request):
    user = authenticate(username=request.data.get("username"), password=request.data.get("password"))
    if not user:
        return Response({"error": "Invalid credentials"}, status=400)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key})


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
    Transaction.objects.create(user=account.user, account=account, amount=amount, transaction_type="withdraw", status="successful")
    return Response({"message": "Withdrawal successful.", "balance": str(account.balance)})


# =========================
# DEPOSIT / PAYMENT
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
            user=request.user, account=account, amount=amount,
            transaction_type="deposit", status="pending", reference=ref,
        )
        site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
        payload  = {
            "tx_ref": ref, "amount": str(amount), "currency": "NGN",
            "redirect_url": f"{site_url}/payment_success/",
            "customer": {
                "email": request.user.email or f"{request.user.username}@placeholder.com",
                "name":  request.user.get_full_name() or request.user.username,
            },
            "customizations": {
                "title": "Wallet Deposit",
                "description": f"Deposit NGN{amount} into your wallet",
            },
        }
        try:
            resp      = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=flw_headers(), timeout=10)
            resp_data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Flutterwave initiation error: {e}")
            transaction.status = "failed"; transaction.save()
            messages.error(request, "Could not connect to payment provider.")
            return redirect("payment")
        if resp_data.get("status") == "success":
            return redirect(resp_data["data"]["link"])
        logger.error(f"Flutterwave error response: {resp_data}")
        transaction.status = "failed"; transaction.save()
        messages.error(request, "Payment initiation failed. Please try again.")
        return redirect("payment")
    return redirect("payment")


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
                messages.error(request, "Invalid amount."); return redirect("payment")
            if amount <= 0:
                messages.error(request, "Amount must be greater than zero."); return redirect("payment")
            account = get_or_create_account(request.user)
            if account.balance < amount:
                return redirect("low_balance")
            account.balance -= amount; account.save()
            Transaction.objects.create(user=request.user, account=account, amount=amount, transaction_type="withdraw", status="successful")
            messages.success(request, f"₦{amount:,} successfully withdrawn.")
            return redirect("succed_trans")
        elif tx_type == "transfer":
            receiver_no = request.POST.get("receiver", "").strip()
            try:
                amount = Decimal(request.POST.get("amount", "0"))
            except InvalidOperation:
                messages.error(request, "Invalid amount."); return redirect("payment")
            if amount <= 0:
                messages.error(request, "Amount must be greater than zero."); return redirect("payment")
            if not receiver_no:
                messages.error(request, "Please enter a recipient account number."); return redirect("payment")
            sender = get_or_create_account(request.user)
            try:
                receiver = Account.objects.get(account_number=receiver_no)
            except Account.DoesNotExist:
                messages.error(request, "Recipient account not found."); return redirect("payment")
            if receiver.user == request.user:
                messages.error(request, "You cannot transfer to your own account."); return redirect("payment")
            if sender.balance < amount:
                return redirect("low_balance")
            with db_transaction.atomic():
                sender.balance -= amount; receiver.balance += amount
                sender.save(); receiver.save()
                Transaction.objects.create(user=request.user, account=sender, amount=amount, transaction_type="transfer", status="successful")
            messages.success(request, f"₦{amount:,} transferred successfully.")
            return redirect("succed_trans")
    return redirect("payment")


# =========================
# DATA — CLUBKONNECT
# =========================

def call_clubkonnect_data_api(network, phone, plan_id, request_id):
    user_id      = config("CLUBKONNECT_USER_ID")
    api_key      = config("CLUBKONNECT_API_KEY")
    network_code = NETWORK_CODES.get(network)
    if not network_code:
        return False, f"Unknown network: {network}"
    url    = "https://www.nellobytesystems.com/APIDatabundleV1.asp"
    params = {
        "UserID": user_id, "APIKey": api_key, "MobileNetwork": network_code,
        "DataPlan": plan_id, "MobileNumber": phone, "RequestID": request_id, "CallBackURL": "",
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
                logger.error(f"ClubKonnect error: {text}"); return False, text
        except json.JSONDecodeError:
            if "successful" in text.lower() or "success" in text.lower():
                return True, text
            logger.error(f"ClubKonnect plain text error: {text}"); return False, text
    except requests.RequestException as e:
        logger.error(f"ClubKonnect request failed: {e}"); return False, "Network error contacting ClubKonnect."


import platform as _platform
import subprocess as _subprocess
_IS_WINDOWS = _platform.system() == "Windows"


def _beewave_via_curl(payload):
    try:
        result = _subprocess.run(
            ["curl", "-s", "-X", "POST", "https://beewave.ng/api/data.php",
             "-H", "Content-Type: application/json", "-d", json.dumps(payload), "--max-time", "30"],
            capture_output=True, text=True, timeout=35,
        )
        raw = result.stdout.strip()
        if not raw: return None, "No response from Beewave."
        return json.loads(raw), None
    except _subprocess.TimeoutExpired: return None, "Beewave request timed out."
    except json.JSONDecodeError:       return None, "Beewave returned unexpected response."
    except FileNotFoundError:          return None, "curl not found on this system."
    except Exception:                  return None, "Network error contacting Beewave."


def _beewave_via_httpx(payload):
    import httpx
    try:
        with httpx.Client(http2=False, timeout=30) as client:
            response = client.post("https://beewave.ng/api/data.php", json=payload)
        if response.status_code != 200:
            return None, f"Beewave server error (HTTP {response.status_code})"
        try:    return response.json(), None
        except: return None, "Beewave returned unexpected response format."
    except httpx.ConnectError:     return None, "Could not connect to Beewave. Please try again."
    except httpx.TimeoutException: return None, "Beewave request timed out. Please try again."
    except Exception:              return None, "Network error contacting Beewave."


def call_beewave_data_api(network, phone, qty, plan_type="sme-data"):
    api_key      = config("BEEWAVE_API_KEY")
    network_name = BEEWAVE_NETWORK_NAMES.get(network)
    if not network_name: return False, f"Unknown network: {network}"
    payload = {"api_key": api_key, "type": plan_type, "qty": qty, "network": network_name, "phone_number": phone}
    logger.info(f"Beewave → network={network_name} plan={qty} phone={phone}")
    data, err = _beewave_via_curl(payload) if _IS_WINDOWS else _beewave_via_httpx(payload)
    if err: return False, err
    status = data.get("status", "")
    if status == "success": return True, data.get("reference", "beewave-ok")
    if status == "pending": return True, data.get("reference", "pending")
    return False, data.get("desc", data.get("message", "Transaction failed"))


@login_required
def buy_data(request):
    if request.method == "POST":
        network = request.POST.get("network", "").strip().upper()
        phone   = request.POST.get("phone_number", "").strip()
        plan_id = request.POST.get("product_code", "").strip()
        if not network or not phone or not plan_id:
            messages.error(request, "Network, phone number, and data plan are required."); return redirect("buy_data")
        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number."); return redirect("buy_data")
        plan_info = next((p for p in DATA_PLANS.get(network, []) if p["id"] == plan_id), None)
        if not plan_info:
            messages.error(request, "Invalid data plan selected."); return redirect("buy_data")
        amount = Decimal(str(plan_info["amount"]))
        try:    customer_account = Account.objects.get(user=request.user)
        except: messages.error(request, "Wallet account not found."); return redirect("home")
        if customer_account.balance < amount: return redirect("low_balance")
        try:    owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_data owner error: {e}"); messages.error(request, "Service temporarily unavailable."); return redirect("buy_data")
        request_id      = str(uuid.uuid4()).replace("-", "")[:20]
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= amount; customer_account.save()
            if not is_owner_buying: owner_account.balance += amount; owner_account.save()
        try:
            success_flag, ck_response = call_clubkonnect_data_api(network, phone, plan_id, request_id)
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount; customer_account.save()
                if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
            messages.error(request, "Something went wrong. Your balance has been refunded."); return redirect("buy_data")
        if success_flag:
            DataPurchase.objects.create(user=request.user, network=network, phone_number=phone, amount=amount, status="successful", reference=request_id)
            messages.success(request, f"{plan_info['label']} purchased successfully for {phone}.")
            return redirect("succed_data")
        with db_transaction.atomic():
            customer_account.balance += amount; customer_account.save()
            if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
        r = ck_response.lower()
        if "insufficient" in r:    error_msg = "Our data provider balance is low. Please try again later."
        elif "invalid api" in r:   error_msg = "API configuration error. Please contact support."
        elif "invalid number" in r: error_msg = "Invalid phone number. Please check and try again."
        else:                      error_msg = f"Purchase failed: {ck_response}. Your balance has been refunded."
        messages.error(request, error_msg)
        DataPurchase.objects.create(user=request.user, network=network, phone_number=phone, amount=amount, status="failed", reference=request_id)
        return redirect("buy_data")
    return render(request, "buy_data.html", {"data_plans_json": json.dumps(DATA_PLANS), "networks": list(DATA_PLANS.keys())})


@login_required
def buy_special_bundle(request):
    if request.method == "POST":
        network = request.POST.get("network", "").strip().upper()
        phone   = request.POST.get("phone_number", "").strip()
        qty     = request.POST.get("qty", "").strip()
        if not network or not phone or not qty:
            messages.error(request, "Network, phone number, and data plan are required."); return redirect("payment")
        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number."); return redirect("payment")
        plan_info = next((p for p in BEEWAVE_PLANS.get(network, []) if p["qty"] == qty), None)
        if not plan_info:
            messages.error(request, "Invalid data plan selected."); return redirect("payment")
        amount    = Decimal(str(plan_info["amount"]))
        plan_type = plan_info.get("type", "sme-data")
        try:    customer_account = Account.objects.get(user=request.user)
        except: messages.error(request, "Wallet account not found."); return redirect("home")
        if customer_account.balance < amount: return redirect("low_balance")
        try:    owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_special_bundle owner error: {e}"); messages.error(request, "Service temporarily unavailable."); return redirect("payment")
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= amount; customer_account.save()
            if not is_owner_buying: owner_account.balance += amount; owner_account.save()
        try:
            success_flag, bw_response = call_beewave_data_api(network, phone, qty, plan_type)
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount; customer_account.save()
                if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
            messages.error(request, "Something went wrong. Your balance has been refunded."); return redirect("payment")
        if success_flag:
            DataPurchase.objects.create(user=request.user, network=network, phone_number=phone, amount=amount, status="successful", reference=str(bw_response))
            messages.success(request, f"{plan_info['label']} purchased successfully for {phone}.")
            return redirect("succed_data")
        with db_transaction.atomic():
            customer_account.balance += amount; customer_account.save()
            if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
        r = bw_response.lower()
        if "insufficient" in r: error_msg = "Our data provider balance is low. Please try again later."
        elif "invalid" in r:    error_msg = "Invalid request. Please check your details and try again."
        elif "timed out" in r:  error_msg = "Request timed out. Please try again in a moment."
        elif "connect" in r:    error_msg = "Could not reach data provider. Please try again shortly."
        else:                   error_msg = f"Purchase failed: {bw_response}. Your balance has been refunded."
        messages.error(request, error_msg)
        DataPurchase.objects.create(user=request.user, network=network, phone_number=phone, amount=amount, status="failed", reference=str(uuid.uuid4()).replace("-", "")[:20])
        return redirect("payment")
    return redirect("payment")


# =========================
# SMM / MARKET
# =========================

def call_jap_api(action, extra_params=None):
    api_key = config("JAP_API_KEY")
    params  = {"key": api_key, "action": action}
    if extra_params: params.update(extra_params)
    try:
        response = requests.post("https://justanotherpanel.com/api/v2", data=params, timeout=15)
        return response.json()
    except Exception as e:
        logger.error(f"JAP API error: {e}"); return None


@login_required
def market(request):
    account           = get_or_create_account(request.user)
    recent_smm_orders = SMMOrder.objects.filter(user=request.user).order_by("-created_at")[:10]
    context = {
        "account": account, "smm_services_json": json.dumps(SMM_SERVICES),
        "platforms": list(SMM_SERVICES.keys()), "recent_orders": recent_smm_orders,
        "platform_labels": {
            "usa_traffic": "🇺🇸 USA Traffic", "uk_traffic": "🇬🇧 UK Traffic",
            "india_traffic": "🇮🇳 India Traffic", "global_traffic": "🌍 Global Traffic",
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
            messages.error(request, "All fields are required."); return redirect("market")
        try:    quantity = int(quantity)
        except: messages.error(request, "Invalid quantity."); return redirect("market")
        if quantity <= 0:
            messages.error(request, "Quantity must be greater than zero."); return redirect("market")
        service_info = next((s for s in SMM_SERVICES.get(platform, []) if s["id"] == service_id), None)
        if not service_info:
            messages.error(request, "Invalid service selected."); return redirect("market")
        if quantity < service_info["min"] or quantity > service_info["max"]:
            messages.error(request, f"Quantity must be between {service_info['min']} and {service_info['max']}."); return redirect("market")
        amount = (Decimal(str(service_info["amount"])) * Decimal(quantity) / Decimal(1000)).quantize(Decimal("0.01"))
        try:    account = Account.objects.get(user=request.user)
        except: messages.error(request, "Wallet account not found."); return redirect("home")
        if account.balance < amount: return redirect("low_balance")
        account.balance -= amount; account.save()
        try:
            result = call_jap_api("add", {"service": service_id, "link": link, "quantity": quantity})
        except Exception as e:
            account.balance += amount; account.save()
            messages.error(request, "Something went wrong. Your balance has been refunded."); return redirect("market")
        if result and "order" in result:
            SMMOrder.objects.create(
                user=request.user, platform=platform, service_name=service_info["label"],
                service_id=service_id, link=link, quantity=quantity, amount=amount,
                jap_order_id=str(result["order"]), status="processing",
            )
            Transaction.objects.create(
                user=request.user, account=account, amount=amount, transaction_type="smm",
                status="successful", description=f"{service_info['label']} x{quantity}",
            )
            messages.success(request, f"Order placed! {service_info['label']} x{quantity} is now processing.")
            return redirect("market")
        account.balance += amount; account.save()
        error_detail = result.get("error", "Unknown error") if result else "No response"
        SMMOrder.objects.create(
            user=request.user, platform=platform, service_name=service_info["label"],
            service_id=service_id, link=link, quantity=quantity, amount=amount, status="failed",
        )
        messages.error(request, f"Order failed: {error_detail}. Your balance has been refunded.")
        return redirect("market")
    return redirect("market")


@login_required
def check_smm_order(request, order_id):
    try:    order = SMMOrder.objects.get(id=order_id, user=request.user)
    except: messages.error(request, "Order not found."); return redirect("market")
    if not order.jap_order_id:
        messages.error(request, "No JAP order ID found for this order."); return redirect("market")
    result = call_jap_api("status", {"order": order.jap_order_id})
    if result and "status" in result:
        status_map = {
            "completed": "completed", "partial": "partial", "cancelled": "cancelled",
            "processing": "processing", "pending": "pending", "in progress": "processing",
        }
        order.status = status_map.get(result["status"].lower(), "processing"); order.save()
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
        return JsonResponse({"error": "Unauthorized."}, status=401)
    try:    payload = json.loads(request.body)
    except: return JsonResponse({"error": "Invalid JSON."}, status=400)
    if payload.get("event") == "charge.completed":
        data = payload.get("data", {})
        if data.get("status") == "successful":
            tx_ref = data.get("tx_ref")
            try:
                transaction_obj = Transaction.objects.get(reference=tx_ref)
                credit_account(transaction_obj)
            except Transaction.DoesNotExist:
                logger.error(f"Webhook: transaction not found for tx_ref={tx_ref}")
    return JsonResponse({"status": "ok"})


def report_view(request):
    if request.method == "POST":
        Report.objects.create(message=request.POST.get("message"))
        messages.success(request, "Report sent!")
        return redirect("report")
    return render(request, "report.html")


# =========================
# FOREIGN NUMBERS — SHARED CONSTANTS
# =========================

FOREIGN_COUNTRIES = [
    "usa", "uk", "canada", "russia", "india", "indonesia",
    "afghanistan", "albania", "algeria", "angola", "argentina",
    "armenia", "australia", "austria", "azerbaijan", "bahrain",
    "bangladesh", "belarus", "belgium", "brazil", "bulgaria",
    "china", "egypt", "france", "germany", "ghana", "italy",
    "japan", "kenya", "malaysia", "mexico", "netherlands",
    "nigeria", "pakistan", "philippines", "poland", "saudi_arabia",
    "singapore", "south_africa", "spain", "sweden", "switzerland",
    "thailand", "turkey", "ukraine", "uae", "vietnam",
]

FOREIGN_COUNTRY_DISPLAY = {
    "usa":          ("United States",        "US", "🇺🇸"),
    "uk":           ("United Kingdom",       "GB", "🇬🇧"),
    "canada":       ("Canada",               "CA", "🇨🇦"),
    "russia":       ("Russia",               "RU", "🇷🇺"),
    "india":        ("India",                "IN", "🇮🇳"),
    "indonesia":    ("Indonesia",            "ID", "🇮🇩"),
    "afghanistan":  ("Afghanistan",          "AF", "🇦🇫"),
    "albania":      ("Albania",              "AL", "🇦🇱"),
    "algeria":      ("Algeria",              "DZ", "🇩🇿"),
    "angola":       ("Angola",               "AO", "🇦🇴"),
    "argentina":    ("Argentina",            "AR", "🇦🇷"),
    "armenia":      ("Armenia",              "AM", "🇦🇲"),
    "australia":    ("Australia",            "AU", "🇦🇺"),
    "austria":      ("Austria",              "AT", "🇦🇹"),
    "azerbaijan":   ("Azerbaijan",           "AZ", "🇦🇿"),
    "bahrain":      ("Bahrain",              "BH", "🇧🇭"),
    "bangladesh":   ("Bangladesh",           "BD", "🇧🇩"),
    "belarus":      ("Belarus",              "BY", "🇧🇾"),
    "belgium":      ("Belgium",              "BE", "🇧🇪"),
    "brazil":       ("Brazil",               "BR", "🇧🇷"),
    "bulgaria":     ("Bulgaria",             "BG", "🇧🇬"),
    "china":        ("China",                "CN", "🇨🇳"),
    "egypt":        ("Egypt",                "EG", "🇪🇬"),
    "france":       ("France",               "FR", "🇫🇷"),
    "germany":      ("Germany",              "DE", "🇩🇪"),
    "ghana":        ("Ghana",                "GH", "🇬🇭"),
    "italy":        ("Italy",                "IT", "🇮🇹"),
    "japan":        ("Japan",                "JP", "🇯🇵"),
    "kenya":        ("Kenya",                "KE", "🇰🇪"),
    "malaysia":     ("Malaysia",             "MY", "🇲🇾"),
    "mexico":       ("Mexico",               "MX", "🇲🇽"),
    "netherlands":  ("Netherlands",          "NL", "🇳🇱"),
    "nigeria":      ("Nigeria",              "NG", "🇳🇬"),
    "pakistan":     ("Pakistan",             "PK", "🇵🇰"),
    "philippines":  ("Philippines",          "PH", "🇵🇭"),
    "poland":       ("Poland",               "PL", "🇵🇱"),
    "saudi_arabia": ("Saudi Arabia",         "SA", "🇸🇦"),
    "singapore":    ("Singapore",            "SG", "🇸🇬"),
    "south_africa": ("South Africa",         "ZA", "🇿🇦"),
    "spain":        ("Spain",                "ES", "🇪🇸"),
    "sweden":       ("Sweden",               "SE", "🇸🇪"),
    "switzerland":  ("Switzerland",          "CH", "🇨🇭"),
    "thailand":     ("Thailand",             "TH", "🇹🇭"),
    "turkey":       ("Turkey",               "TR", "🇹🇷"),
    "ukraine":      ("Ukraine",              "UA", "🇺🇦"),
    "uae":          ("United Arab Emirates", "AE", "🇦🇪"),
    "vietnam":      ("Vietnam",              "VN", "🇻🇳"),
}

FOREIGN_SERVICES = [
    "whatsapp", "telegram", "google", "facebook",
    "instagram", "twitter", "tiktok", "snapchat",
    "discord", "netflix", "amazon", "microsoft",
    "apple", "uber", "airbnb", "spotify",
    "paypal", "linkedin", "viber", "line",
]

FOREIGN_SERVICE_DISPLAY = {
    "whatsapp":  ("WhatsApp",   "💬"),
    "telegram":  ("Telegram",   "✈️"),
    "google":    ("Google",     "🔍"),
    "facebook":  ("Facebook",   "📘"),
    "instagram": ("Instagram",  "📸"),
    "twitter":   ("Twitter/X",  "🐦"),
    "tiktok":    ("TikTok",     "🎵"),
    "snapchat":  ("Snapchat",   "👻"),
    "discord":   ("Discord",    "🎮"),
    "netflix":   ("Netflix",    "🎬"),
    "amazon":    ("Amazon",     "📦"),
    "microsoft": ("Microsoft",  "🪟"),
    "apple":     ("Apple",      "🍎"),
    "uber":      ("Uber",       "🚗"),
    "airbnb":    ("Airbnb",     "🏠"),
    "spotify":   ("Spotify",    "🎧"),
    "paypal":    ("PayPal",     "💳"),
    "linkedin":  ("LinkedIn",   "💼"),
    "viber":     ("Viber",      "📞"),
    "line":      ("Line",       "🟢"),
}

FIVESIM_COUNTRY_MAP = {
    "usa": "usa", "uk": "england", "canada": "canada", "russia": "russia",
    "india": "india", "indonesia": "indonesia", "afghanistan": "afghanistan",
    "albania": "albania", "algeria": "algeria", "angola": "angola",
    "argentina": "argentina", "armenia": "armenia", "australia": "australia",
    "austria": "austria", "azerbaijan": "azerbaijan", "bahrain": "bahrain",
    "bangladesh": "bangladesh", "belarus": "belarus", "belgium": "belgium",
    "brazil": "brazil", "bulgaria": "bulgaria", "china": "china",
    "egypt": "egypt", "france": "france", "germany": "germany",
    "ghana": "ghana", "italy": "italy", "japan": "japan", "kenya": "kenya",
    "malaysia": "malaysia", "mexico": "mexico", "netherlands": "netherlands",
    "nigeria": "nigeria", "pakistan": "pakistan", "philippines": "philippines",
    "poland": "poland", "saudi_arabia": "saudiarabia", "singapore": "singapore",
    "south_africa": "southafrica", "spain": "spain", "sweden": "sweden",
    "switzerland": "switzerland", "thailand": "thailand", "turkey": "turkey",
    "ukraine": "ukraine", "uae": "uae", "vietnam": "vietnam",
}

FIVESIM_SERVICE_MAP = {
    "whatsapp": "whatsapp", "telegram": "telegram", "google": "google",
    "facebook": "facebook", "instagram": "instagram", "twitter": "twitter",
    "tiktok": "tiktok", "snapchat": "snapchat", "discord": "discord",
    "netflix": "netflix", "amazon": "amazon", "microsoft": "microsoft",
    "apple": "apple", "uber": "uber", "airbnb": "airbnb", "spotify": "spotify",
    "paypal": "paypal", "linkedin": "linkedin", "viber": "viber", "line": "line",
}


# =========================
# FOREIGN NUMBERS — 5SIM
# =========================

def _ngn_price(usd_price):
    import math
    def clean(val):
        return str(val).split("#")[0].strip().strip('"').strip("'")
    try:
        rate   = Decimal(clean(config("USD_TO_NGN_RATE",      default="1600")))
        markup = Decimal(clean(config("FOREIGN_NUMBER_MARKUP", default="1.3")))
    except Exception as e:
        logger.error(f"_ngn_price config error: {e}")
        rate = Decimal("1600"); markup = Decimal("1.3")
    ngn = Decimal(str(usd_price)) * rate * markup
    return Decimal(str(math.ceil(float(ngn) / 10) * 10))


def _fetch_5sim_prices(country=None, service=None):
    try:
        response = requests.get("https://5sim.net/v1/guest/prices", timeout=30)
        data     = response.json()
    except Exception as e:
        logger.error(f"5SIM price fetch error: {e}")
        return []
    prices    = []
    countries = [country] if country else FOREIGN_COUNTRIES
    services  = [service] if service  else FOREIGN_SERVICES
    for c in countries:
        fivesim_c = FIVESIM_COUNTRY_MAP.get(c, c)
        if fivesim_c not in data:
            logger.debug(f"5SIM prices: '{fivesim_c}' not found (slug='{c}')")
            continue
        for s in services:
            fivesim_s = FIVESIM_SERVICE_MAP.get(s, s)
            if fivesim_s not in data[fivesim_c]:
                continue
            for operator_name, operator_data in data[fivesim_c][fivesim_s].items():
                usd = operator_data.get("cost", 0)
                prices.append({
                    "country":   c,
                    "service":   s,
                    "operator":  operator_name,
                    "price_usd": usd,
                    "price_ngn": float(_ngn_price(usd)),
                    "price":     float(_ngn_price(usd)),
                    "count":     operator_data.get("count", 0),
                })
    return prices


def _fivesim_headers():
    return {
        "Authorization": f"Bearer {config('FIVE_SIM_API_KEY').strip()}",
        "Accept": "application/json",
    }


@login_required
def buy_foreign_number(request):
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
            return redirect(f"/buy-foreign-number/?country={country}&service={service}")
        cheapest       = min(available, key=lambda x: x["price_ngn"])
        selected_price = Decimal(str(cheapest["price_ngn"]))
        if customer_account.balance < selected_price:
            messages.error(request, f"Insufficient balance. You need ₦{selected_price:,} for this number.")
            return redirect("buy_foreign_number")
        try:
            owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_foreign_number owner error: {e}")
            messages.error(request, "Service temporarily unavailable. Please try again later.")
            return redirect("buy_foreign_number")
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= selected_price; customer_account.save()
            if not is_owner_buying: owner_account.balance += selected_price; owner_account.save()
        fivesim_country = FIVESIM_COUNTRY_MAP.get(country, country)
        fivesim_service = FIVESIM_SERVICE_MAP.get(service, service)
        try:
            buy_url  = f"https://5sim.net/v1/user/buy/activation/{fivesim_country}/any/{fivesim_service}"
            logger.info(f"5SIM buy → {buy_url} | slug=({country},{service}) | price=₦{selected_price}")
            response = requests.get(buy_url, headers=_fivesim_headers(), timeout=30)
            logger.info(f"5SIM buy ← HTTP {response.status_code} | {response.text[:300]}")
            if response.status_code == 200:
                data = response.json()
                ForeignNumber.objects.create(
                    user=request.user, order_id=data.get("id"), country=country,
                    service=service, phone_number=data.get("phone"),
                    price=selected_price, status="PENDING",
                )
                messages.success(request, f"Number {data.get('phone')} purchased successfully!")
            else:
                with db_transaction.atomic():
                    customer_account.balance += selected_price; customer_account.save()
                    if not is_owner_buying: owner_account.balance -= selected_price; owner_account.save()
                err_msg = f"HTTP {response.status_code}"
                try:
                    err_data = response.json()
                    err_msg  = err_data.get("message") or err_data.get("error") or err_data.get("msg") or str(err_data)
                except Exception:
                    if response.text.strip(): err_msg = response.text.strip()
                logger.error(f"5SIM buy failed: HTTP {response.status_code} | {err_msg}")
                err_lower = str(err_msg).lower()
                if "no free phones" in err_lower or "no numbers" in err_lower:
                    messages.error(request, "No available numbers right now. Try another country or service.")
                elif "not enough user balance" in err_lower or "not enough balance" in err_lower:
                    messages.error(request, "5SIM provider balance is low. Contact support.")
                elif "bad country" in err_lower or "bad product" in err_lower:
                    messages.error(request, "Invalid country or service. Please try again.")
                elif response.status_code == 401:
                    messages.error(request, "5SIM authentication error. Contact support.")
                elif response.status_code == 400:
                    messages.error(request, f"5SIM rejected the request: {err_msg}. Balance refunded.")
                else:
                    messages.error(request, f"Purchase failed ({response.status_code}): {err_msg}. Balance refunded.")
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += selected_price; customer_account.save()
                if not is_owner_buying: owner_account.balance -= selected_price; owner_account.save()
            logger.error(f"5SIM buy exception: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
        return redirect(f"/buy-foreign-number/?country={country}&service={service}")
    numbers = ForeignNumber.objects.filter(user=request.user).order_by("-created_at")
    context = {
        "account": customer_account, "countries": FOREIGN_COUNTRIES, "services": FOREIGN_SERVICES,
        "country_display": FOREIGN_COUNTRY_DISPLAY, "service_display": FOREIGN_SERVICE_DISPLAY,
        "numbers": numbers, "prices": prices,
        "selected_country": selected_country, "selected_service": selected_service,
    }
    return render(request, "buy_foreign_number.html", context)


@login_required
def foreign_number_prices(request):
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

    if foreign_number.status == "CANCELLED":
        messages.error(request, "This number is already cancelled.")
        return redirect("buy_foreign_number")

    try:
        response = requests.get(
            f"https://5sim.net/v1/user/cancel/{order_id}",
            headers=_fivesim_headers(), timeout=30,
        )
        logger.info(f"5SIM cancel → HTTP {response.status_code} | {response.text[:200]}")
        if response.status_code == 200:
            with db_transaction.atomic():
                foreign_number.status = "CANCELLED"
                foreign_number.save()
                # Refund customer
                customer_account = Account.objects.select_for_update().get(user=request.user)
                customer_account.balance += foreign_number.price
                customer_account.save()
                # Deduct from owner to keep books balanced
                try:
                    owner_account = get_owner_account()
                    if owner_account.pk != customer_account.pk:
                        owner_acc = Account.objects.select_for_update().get(pk=owner_account.pk)
                        owner_acc.balance -= foreign_number.price
                        owner_acc.save()
                except Exception as e:
                    logger.error(f"Owner balance deduct on 5SIM cancel failed: {e}")
            messages.success(request, f"Number cancelled. ₦{foreign_number.price:,} refunded to your wallet.")
        else:
            messages.error(request, "Unable to cancel number. It may have already expired.")
    except Exception as e:
        logger.error(f"5SIM cancel error: {e}")
        messages.error(request, "Something went wrong while cancelling. Please try again.")
    return redirect("buy_foreign_number")


# =========================
# FOREIGN NUMBERS — STEADYSIM
# =========================

STEADYSIM_BASE = "https://steadysim.com/stubs/handler_api.php"

STEADYSIM_COUNTRY_IDS = {
    "usa": "187", "uk": "16", "canada": "36", "russia": "0", "india": "22",
    "indonesia": "6", "afghanistan": "185", "albania": "62", "algeria": "59",
    "angola": "116", "argentina": "8", "armenia": "51", "australia": "26",
    "austria": "90", "azerbaijan": "73", "bahrain": "107", "bangladesh": "50",
    "belarus": "86", "belgium": "95", "brazil": "7", "bulgaria": "55",
    "china": "46", "egypt": "39", "france": "78", "germany": "43",
    "ghana": "140", "italy": "35", "japan": "33", "kenya": "109",
    "malaysia": "12", "mexico": "13", "netherlands": "102", "nigeria": "109",
    "pakistan": "11", "philippines": "4", "poland": "15", "saudi_arabia": "101",
    "singapore": "41", "south_africa": "126", "spain": "65", "sweden": "134",
    "switzerland": "76", "thailand": "5", "turkey": "3", "ukraine": "1",
    "uae": "230", "vietnam": "10",
}

STEADYSIM_SERVICE_CODES = {
    "whatsapp": "wa", "telegram": "tg", "google": "go", "facebook": "fb",
    "instagram": "ig", "twitter": "tw", "tiktok": "tt", "snapchat": "sc",
    "discord": "ds", "netflix": "nf", "amazon": "am", "microsoft": "ms",
    "apple": "ap", "uber": "ub", "airbnb": "ab", "spotify": "sf",
    "paypal": "pp", "linkedin": "li", "viber": "vi", "line": "ln",
}


def _steadysim_get(params):
    params["api_key"] = config("STEADYSIM_API_KEY")
    try:
        resp = requests.get(STEADYSIM_BASE, params=params, timeout=15)
        return resp.text.strip()
    except requests.RequestException as e:
        logger.error(f"SteadySim request error: {e}"); return None


def _fetch_steadysim_price(country, service):
    country_id   = STEADYSIM_COUNTRY_IDS.get(country)
    service_code = STEADYSIM_SERVICE_CODES.get(service)
    if not country_id or not service_code: return None
    raw = _steadysim_get({"action": "getPrices", "country": country_id, "service": service_code})
    if not raw: return None
    if raw.startswith("BAD_KEY") or raw.startswith("COUNTRY_AND_SERVICE_REQUIRED"):
        logger.error(f"SteadySim getPrices error: {raw}"); return None
    try:
        data     = json.loads(raw)
        entry    = data.get(country_id, {}).get(service_code, {})
        cost_usd = entry.get("cost", 0)
        count    = entry.get("count", 0)
        if count <= 0: return None
        return {"cost_usd": cost_usd, "price_ngn": int(_ngn_price(cost_usd)), "count": count, "provider": "steadysim"}
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"SteadySim getPrices parse error: {e} | raw: {raw[:200]}"); return None


def call_steadysim_buy_number(country, service):
    country_id   = STEADYSIM_COUNTRY_IDS.get(country)
    service_code = STEADYSIM_SERVICE_CODES.get(service)
    if not country_id or not service_code:
        return False, f"Unsupported country or service: {country}/{service}", None
    raw = _steadysim_get({"action": "getNumber", "country": country_id, "service": service_code})
    if raw is None: return False, "Could not connect to SteadySim.", None
    if raw.startswith("ACCESS_NUMBER:"):
        parts = raw.split(":")
        if len(parts) >= 3: return True, parts[1], parts[2]
        return False, "Unexpected SteadySim response format.", None
    error_map = {
        "NO_NUMBERS": "No numbers available right now. Try another country or service.",
        "NO_BALANCE": "SteadySim provider balance is low. Contact support.",
        "BAD_KEY":    "SteadySim API key error. Contact support.",
    }
    return False, error_map.get(raw, f"SteadySim error: {raw}"), None


def call_steadysim_cancel(activation_id):
    raw = _steadysim_get({"action": "setStatus", "id": activation_id, "status": "8"})
    if raw is None: return False, "Network error."
    if raw == "ACCESS_CANCEL": return True, "Cancelled."
    return False, f"SteadySim cancel response: {raw}"


def call_steadysim_check_sms(activation_id):
    raw = _steadysim_get({"action": "getStatus", "id": activation_id})
    if raw is None: return "error", None
    if raw == "STATUS_WAIT_CODE": return "waiting", None
    if raw.startswith("STATUS_OK:"): return "received", raw.split(":", 1)[1]
    if raw == "STATUS_CANCEL": return "cancelled", None
    return "error", None


@login_required
def buy_foreign_number_steadysim(request):
    customer_account = get_or_create_account(request.user)
    selected_country = request.GET.get("country", "") or request.POST.get("country", "")
    selected_service = request.GET.get("service", "") or request.POST.get("service", "")
    if request.method == "GET" and request.GET.get("fetch_price"):
        country  = request.GET.get("country", "").strip().lower()
        service  = request.GET.get("service", "").strip().lower()
        info     = _fetch_steadysim_price(country, service)
        if info: return JsonResponse({"available": True, **info})
        return JsonResponse({"available": False})
    if request.method == "POST":
        country = request.POST.get("country", "").strip().lower()
        service = request.POST.get("service", "").strip().lower()
        if not country or not service:
            messages.error(request, "Please select a country and service."); return redirect("buy_foreign_number_steadysim")
        if country not in FOREIGN_COUNTRIES:
            messages.error(request, "Invalid country selected."); return redirect("buy_foreign_number_steadysim")
        if service not in FOREIGN_SERVICES:
            messages.error(request, "Invalid service selected."); return redirect("buy_foreign_number_steadysim")
        price_info = _fetch_steadysim_price(country, service)
        if not price_info:
            messages.error(request, "No numbers available right now. Try another option.")
            return redirect(f"/buy-foreign-number-steadysim/?country={country}&service={service}")
        charge = Decimal(str(price_info["price_ngn"]))
        if customer_account.balance < charge:
            messages.error(request, f"Insufficient balance. You need ₦{charge:,} for this number.")
            return redirect("buy_foreign_number_steadysim")
        try:    owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_foreign_number_steadysim owner error: {e}")
            messages.error(request, "Service temporarily unavailable."); return redirect("buy_foreign_number_steadysim")
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= charge; customer_account.save()
            if not is_owner_buying: owner_account.balance += charge; owner_account.save()
        try:
            ok, activation_id_or_err, phone_number = call_steadysim_buy_number(country, service)
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += charge; customer_account.save()
                if not is_owner_buying: owner_account.balance -= charge; owner_account.save()
            logger.error(f"SteadySim buy crashed: {e}")
            messages.error(request, "Something went wrong. Your balance has been refunded.")
            return redirect("buy_foreign_number_steadysim")
        if ok:
            ForeignNumber.objects.create(
                user=request.user, order_id=activation_id_or_err, country=country,
                service=service, phone_number=phone_number, price=charge, status="PENDING",
            )
            messages.success(request, f"Number {phone_number} purchased via SteadySim successfully!")
        else:
            with db_transaction.atomic():
                customer_account.balance += charge; customer_account.save()
                if not is_owner_buying: owner_account.balance -= charge; owner_account.save()
            messages.error(request, activation_id_or_err)
        return redirect(f"/buy-foreign-number-steadysim/?country={country}&service={service}")
    numbers = ForeignNumber.objects.filter(user=request.user).order_by("-created_at")
    context = {
        "account": customer_account, "countries": FOREIGN_COUNTRIES, "services": FOREIGN_SERVICES,
        "country_display": FOREIGN_COUNTRY_DISPLAY, "service_display": FOREIGN_SERVICE_DISPLAY,
        "numbers": numbers, "selected_country": selected_country, "selected_service": selected_service,
    }
    return render(request, "buy_foreign_number_steadysim.html", context)


@login_required
def cancel_foreign_number_steadysim(request, order_id):
    try:
        foreign_number = ForeignNumber.objects.get(order_id=order_id, user=request.user)
    except ForeignNumber.DoesNotExist:
        messages.error(request, "Number not found.")
        return redirect("buy_foreign_number_steadysim")

    if foreign_number.status == "CANCELLED":
        messages.error(request, "This number is already cancelled.")
        return redirect("buy_foreign_number_steadysim")

    ok, msg = call_steadysim_cancel(order_id)
    if ok:
        with db_transaction.atomic():
            foreign_number.status = "CANCELLED"
            foreign_number.save()
            # Refund customer
            customer_account = Account.objects.select_for_update().get(user=request.user)
            customer_account.balance += foreign_number.price
            customer_account.save()
            # Deduct from owner to keep books balanced
            try:
                owner_account = get_owner_account()
                if owner_account.pk != customer_account.pk:
                    owner_acc = Account.objects.select_for_update().get(pk=owner_account.pk)
                    owner_acc.balance -= foreign_number.price
                    owner_acc.save()
            except Exception as e:
                logger.error(f"Owner balance deduct on SteadySim cancel failed: {e}")
        messages.success(request, f"Number cancelled. ₦{foreign_number.price:,} refunded to your wallet.")
    else:
        messages.error(request, f"Could not cancel: {msg}")
    return redirect("buy_foreign_number_steadysim")


# =========================
# ELECTRICITY — CLUBKONNECT
# =========================

ELECTRIC_COMPANIES = {
    "01": "Eko Electric (EKEDC)",         "02": "Ikeja Electric (IKEDC)",
    "03": "Abuja Electric (AEDC)",         "04": "Kano Electric (KEDC)",
    "05": "Portharcourt Electric (PHEDC)", "06": "Jos Electric (JEDC)",
    "07": "Ibadan Electric (IBEDC)",       "08": "Kaduna Electric (KAEDC)",
    "09": "Enugu Electric (EEDC)",         "10": "Benin Electric (BEDC)",
    "11": "Yola Electric (YEDC)",          "12": "Aba Electric (APLE)",
}
METER_TYPES = {"01": "Prepaid", "02": "Postpaid"}


def verify_meter(electric_company, meter_no, meter_type):
    user_id = config("CLUBKONNECT_USER_ID"); api_key = config("CLUBKONNECT_API_KEY")
    url = (
        f"https://www.nellobytesystems.com/APIVerifyElectricityV1.asp"
        f"?UserID={user_id}&APIKey={api_key}&ElectricCompany={electric_company}"
        f"&MeterNo={meter_no}&MeterType={meter_type}"
    )
    try:
        resp = requests.get(url, timeout=15); data = resp.json()
        name = data.get("customer_name", "")
        if name and name != "INVALID_METERNO": return True, name
        return False, "Invalid meter number"
    except Exception as e:
        logger.error(f"Meter verify error: {e}"); return False, "Could not verify meter number"


def call_clubkonnect_electricity_api(electric_company, meter_type, meter_no, amount, phone, request_id):
    user_id  = config("CLUBKONNECT_USER_ID"); api_key = config("CLUBKONNECT_API_KEY")
    site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
    url = (
        f"https://www.nellobytesystems.com/APIElectricityV1.asp"
        f"?UserID={user_id}&APIKey={api_key}&ElectricCompany={electric_company}"
        f"&MeterType={meter_type}&MeterNo={meter_no}&Amount={amount}"
        f"&PhoneNo={phone}&RequestID={request_id}&CallBackURL={site_url}/webhook/clubkonnect/"
    )
    try:
        resp = requests.get(url, timeout=15); text = resp.text.strip()
        try:
            data = json.loads(text); status = data.get("status", ""); sc = str(data.get("statuscode", ""))
            if status == "ORDER_RECEIVED" or sc == "100":
                return True, data.get("metertoken", ""), data.get("orderid", "")
            elif status == "INSUFFICIENT_BALANCE":
                return False, "insufficient balance in provider wallet", ""
            elif status in ("INVALID_CREDENTIALS", "INVALID_APIKEY"):
                return False, "invalid api credentials", ""
            elif status == "INVALID_MeterNo":
                return False, "invalid meter number", ""
            else:
                return False, text, ""
        except json.JSONDecodeError:
            return False, text, ""
    except requests.RequestException as e:
        return False, "Network error contacting ClubKonnect.", ""


@login_required
def buy_electricity(request):
    account = get_or_create_account(request.user)
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
            messages.error(request, "All fields are required."); return redirect("buy_electricity")
        try:    amount = Decimal(amount_raw)
        except: messages.error(request, "Invalid amount."); return redirect("buy_electricity")
        if amount < 1000:
            messages.error(request, "Minimum electricity purchase is ₦1,000."); return redirect("buy_electricity")
        if company not in ELECTRIC_COMPANIES:
            messages.error(request, "Invalid electricity company selected."); return redirect("buy_electricity")
        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number."); return redirect("buy_electricity")
        try:    customer_account = Account.objects.get(user=request.user)
        except: messages.error(request, "Wallet account not found."); return redirect("home")
        if customer_account.balance < amount: return redirect("low_balance")
        try:    owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_electricity owner error: {e}")
            messages.error(request, "Service temporarily unavailable."); return redirect("buy_electricity")
        request_id      = str(uuid.uuid4()).replace("-", "")[:20]
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= amount; customer_account.save()
            if not is_owner_buying: owner_account.balance += amount; owner_account.save()
        try:
            success_flag, token, order_id = call_clubkonnect_electricity_api(
                company, meter_type, meter_no, int(amount), phone, request_id,
            )
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount; customer_account.save()
                if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
            messages.error(request, "Something went wrong. Your balance has been refunded."); return redirect("buy_electricity")
        if success_flag:
            ElectricityPurchase.objects.create(
                user=request.user,
                electric_provider=ELECTRIC_COMPANIES.get(company, company),
                meter_type=METER_TYPES.get(meter_type, meter_type),
                meter_number=meter_no, amount=amount, token=token,
                reference=request_id, status="successful",
            )
            messages.success(request, f"₦{amount:,} electricity purchased! Token: {token}")
            return redirect("buy_electricity")
        with db_transaction.atomic():
            customer_account.balance += amount; customer_account.save()
            if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
        messages.error(request, f"Purchase failed: {token}. Your balance has been refunded.")
        return redirect("buy_electricity")
    purchases = ElectricityPurchase.objects.filter(user=request.user).order_by("-created_at")[:10]
    return render(request, "buy_electricity.html", {
        "account": account, "companies": ELECTRIC_COMPANIES,
        "meter_types": METER_TYPES, "purchases": purchases,
    })


# =========================
# CABLE TV — CLUBKONNECT
# =========================

CABLE_TV_PROVIDERS = {"dstv": "DStv", "gotv": "GOtv", "startimes": "StarTimes", "showmax": "Showmax"}

CABLE_TV_PACKAGES = {
    "dstv": [
        {"code": "dstv-padi",    "label": "DStv Padi",                     "amount": 4600},
        {"code": "dstv-yanga",   "label": "DStv Yanga",                    "amount": 6200},
        {"code": "dstv-confam",  "label": "DStv Confam",                   "amount": 11400},
        {"code": "dstv79",       "label": "DStv Compact",                  "amount": 19500},
        {"code": "dstv7",        "label": "DStv Compact Plus",             "amount": 30500},
        {"code": "dstv3",        "label": "DStv Premium",                  "amount": 45000},
        {"code": "confam-extra", "label": "DStv Confam + ExtraView",       "amount": 17000},
        {"code": "yanga-extra",  "label": "DStv Yanga + ExtraView",        "amount": 12000},
        {"code": "padi-extra",   "label": "DStv Padi + ExtraView",         "amount": 10400},
        {"code": "dstv30",       "label": "DStv Compact + ExtraView",      "amount": 25000},
        {"code": "dstv33",       "label": "DStv Premium + ExtraView",      "amount": 50500},
        {"code": "dstv45",       "label": "DStv Compact Plus + ExtraView", "amount": 36000},
    ],
    "gotv": [
        {"code": "gotv-smallie", "label": "GOtv Smallie", "amount": 2200},
        {"code": "gotv-jinja",   "label": "GOtv Jinja",   "amount": 4200},
        {"code": "gotv-jolli",   "label": "GOtv Jolli",   "amount": 6100},
        {"code": "gotv-max",     "label": "GOtv Max",     "amount": 8700},
        {"code": "gotv-super",   "label": "GOtv Super",   "amount": 11700},
    ],
    "startimes": [
        {"code": "nova_weekly",    "label": "StarTimes Nova Weekly",     "amount": 900},
        {"code": "basic_weekly",   "label": "StarTimes Basic Weekly",    "amount": 1600},
        {"code": "classic_weekly", "label": "StarTimes Classic Weekly",  "amount": 2200},
        {"code": "smart_weekly",   "label": "StarTimes Smart Weekly",    "amount": 1900},
        {"code": "super_weekly",   "label": "StarTimes Super Weekly",    "amount": 3400},
        {"code": "nova",           "label": "StarTimes Nova Monthly",    "amount": 2300},
        {"code": "basic",          "label": "StarTimes Basic Monthly",   "amount": 4200},
        {"code": "classic",        "label": "StarTimes Classic Monthly", "amount": 6200},
        {"code": "smart",          "label": "StarTimes Smart Monthly",   "amount": 5300},
        {"code": "super",          "label": "StarTimes Super Monthly",   "amount": 9700},
    ],
    "showmax": [
        {"code": "showmax",                "label": "Showmax Mobile",         "amount": 2900},
        {"code": "showmax-premier-league", "label": "Showmax Premier League", "amount": 3600},
    ],
}


def verify_smartcard(cable_tv, smartcard_no):
    user_id = config("CLUBKONNECT_USER_ID"); api_key = config("CLUBKONNECT_API_KEY")
    url = (
        f"https://www.nellobytesystems.com/APIVerifyCableTVV1.asp"
        f"?UserID={user_id}&APIKey={api_key}&CableTV={cable_tv}&SmartCardNo={smartcard_no}"
    )
    try:
        resp = requests.get(url, timeout=15); data = resp.json(); name = data.get("customer_name", "")
        if name and name != "INVALID_SMARTCARDNO": return True, name
        return False, "Invalid smartcard number"
    except Exception as e:
        logger.error(f"Smartcard verify error: {e}"); return False, "Could not verify smartcard"


def call_clubkonnect_cabletv_api(cable_tv, package, smartcard_no, phone, request_id):
    user_id  = config("CLUBKONNECT_USER_ID"); api_key = config("CLUBKONNECT_API_KEY")
    site_url = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
    url = (
        f"https://www.nellobytesystems.com/APICableTVV1.asp"
        f"?UserID={user_id}&APIKey={api_key}&CableTV={cable_tv}&Package={package}"
        f"&SmartCardNo={smartcard_no}&PhoneNo={phone}&RequestID={request_id}"
        f"&CallBackURL={site_url}/webhook/clubkonnect/"
    )
    try:
        resp = requests.get(url, timeout=15); text = resp.text.strip()
        try:
            data = json.loads(text); status = data.get("status", ""); sc = str(data.get("statuscode", ""))
            if status == "ORDER_RECEIVED" or sc == "100":
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
                return False, text
        except json.JSONDecodeError:
            return False, text
    except requests.RequestException as e:
        return False, "Network error contacting ClubKonnect."


@login_required
def buy_cable_tv(request):
    account = get_or_create_account(request.user)
    if request.method == "GET" and request.GET.get("verify_card"):
        ok, result = verify_smartcard(request.GET.get("cable_tv", ""), request.GET.get("smartcard_no", ""))
        return JsonResponse({"success": ok, "customer_name": result if ok else "", "error": result if not ok else ""})
    if request.method == "GET" and request.GET.get("get_packages"):
        return JsonResponse({"packages": CABLE_TV_PACKAGES.get(request.GET.get("cable_tv", ""), [])})
    if request.method == "POST":
        cable_tv     = request.POST.get("cable_tv", "").strip().lower()
        package_code = request.POST.get("package", "").strip()
        smartcard_no = request.POST.get("smartcard_no", "").strip()
        phone        = request.POST.get("phone", "").strip()
        if not all([cable_tv, package_code, smartcard_no, phone]):
            messages.error(request, "All fields are required."); return redirect("buy_cable_tv")
        if cable_tv not in CABLE_TV_PROVIDERS:
            messages.error(request, "Invalid cable TV provider."); return redirect("buy_cable_tv")
        if len(phone) < 11:
            messages.error(request, "Enter a valid 11-digit phone number."); return redirect("buy_cable_tv")
        package_info = next((p for p in CABLE_TV_PACKAGES.get(cable_tv, []) if p["code"] == package_code), None)
        if not package_info:
            messages.error(request, "Invalid package selected."); return redirect("buy_cable_tv")
        amount = Decimal(str(package_info["amount"]))
        try:    customer_account = Account.objects.get(user=request.user)
        except: messages.error(request, "Wallet account not found."); return redirect("home")
        if customer_account.balance < amount: return redirect("low_balance")
        try:    owner_account = get_owner_account()
        except Exception as e:
            logger.error(f"buy_cable_tv owner error: {e}")
            messages.error(request, "Service temporarily unavailable."); return redirect("buy_cable_tv")
        request_id      = str(uuid.uuid4()).replace("-", "")[:20]
        is_owner_buying = (customer_account.pk == owner_account.pk)
        with db_transaction.atomic():
            customer_account.balance -= amount; customer_account.save()
            if not is_owner_buying: owner_account.balance += amount; owner_account.save()
        try:
            success_flag, ck_response = call_clubkonnect_cabletv_api(
                cable_tv, package_code, smartcard_no, phone, request_id,
            )
        except Exception as e:
            with db_transaction.atomic():
                customer_account.balance += amount; customer_account.save()
                if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
            messages.error(request, "Something went wrong. Your balance has been refunded."); return redirect("buy_cable_tv")
        if success_flag:
            CableTVPurchase.objects.create(
                user=request.user, provider=cable_tv,
                provider_name=CABLE_TV_PROVIDERS.get(cable_tv, cable_tv),
                package_code=package_code, package_name=package_info["label"],
                smartcard_no=smartcard_no, phone=phone, amount=amount,
                order_id=ck_response, reference=request_id, status="successful",
            )
            messages.success(request, f"{package_info['label']} subscription successful for {smartcard_no}!")
            return redirect("buy_cable_tv")
        with db_transaction.atomic():
            customer_account.balance += amount; customer_account.save()
            if not is_owner_buying: owner_account.balance -= amount; owner_account.save()
        r = ck_response.lower()
        if "insufficient" in r:        error_msg = "Provider balance is low. Please try again later."
        elif "invalid smartcard" in r:  error_msg = "Invalid smartcard number. Please check and try again."
        elif "not available" in r:      error_msg = "Selected package is currently unavailable."
        else:                           error_msg = f"Subscription failed: {ck_response}. Your balance has been refunded."
        messages.error(request, error_msg)
        return redirect("buy_cable_tv")
    purchases = CableTVPurchase.objects.filter(user=request.user).order_by("-created_at")[:10]
    return render(request, "buy_cable_tv.html", {
        "account": account, "providers": CABLE_TV_PROVIDERS,
        "packages": json.dumps(CABLE_TV_PACKAGES), "purchases": purchases,
    })