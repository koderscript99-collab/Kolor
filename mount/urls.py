"""
urls.py — add these paths to your existing urlpatterns.
All existing URLs are preserved; the two SteadySim routes are new.
"""

from django.urls import path
from . import views

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────────────
    path("",              views.landing_page,  name="landing"),
    path("signup/",       views.signup,        name="signup"),
    path("login/",        views.login_view,    name="login"),
    path("logout/",       views.logout_view,   name="logout"),

    # ── Core pages ────────────────────────────────────────────────────────
    path("home/",         views.home,          name="home"),
    path("payment/",      views.payment,       name="payment"),
    path("report/",       views.report,        name="report"),
    path("success/",      views.success,       name="success"),
    path("succed-data/",  views.succed_data,   name="succed_data"),
    path("succed-trans/", views.succed_trans,  name="succed_trans"),
    path("low-balance/",  views.low_balance,   name="low_balance"),
    path("transfer/",     views.transfer,      name="transfer"),

    # ── Wallet / transactions ─────────────────────────────────────────────
    path("deposit/",          views.deposit,          name="deposit"),
    path("payment_success/",  views.payment_success,  name="payment_success"),
    path("transaction/",      views.transaction,      name="transaction"),

    # ── Data purchase ─────────────────────────────────────────────────────
    path("buy-data/",          views.buy_data,          name="buy_data"),
    

    # ── SMM ───────────────────────────────────────────────────────────────
    path("market/",                        views.market,          name="market"),

    # ── 5SIM foreign numbers (primary provider) ───────────────────────────
    path("buy-foreign-number/",
         views.buy_foreign_number,
         name="buy_foreign_number"),

    path("buy-foreign-number/prices/",
         views.foreign_number_prices,
         name="foreign_prices"),

    path("buy-foreign-number/cancel/<str:order_id>/",
         views.cancel_foreign_number,
         name="cancel_foreign_number"),

    # ── SteadySim foreign numbers (second provider) ── NEW ────────────────
    path("buy-foreign-number-steadysim/",
         views.buy_foreign_number_steadysim,
         name="buy_foreign_number_steadysim"),

    path("buy-foreign-number-steadysim/cancel/<str:order_id>/",
         views.cancel_foreign_number_steadysim,
         name="cancel_foreign_number_steadysim"),

    # ── Electricity ───────────────────────────────────────────────────────
    path("buy-electricity/", views.buy_electricity, name="buy_electricity"),

    # ── Cable TV ─────────────────────────────────────────────────────────
    path("buy-cable-tv/", views.buy_cable_tv, name="buy_cable_tv"),

    # ── Profile (DRF) ────────────────────────────────────────────────────
    path("api/profile/",        views.get_profile,    name="get_profile"),
    path("api/profile/update/", views.update_profile, name="update_profile"),
    path("api/login/",          views.api_login,      name="api_login"),
    path("api/withdraw/",       views.withdraw,        name="api_withdraw"),

    # ── Webhooks ─────────────────────────────────────────────────────────
    path("webhook/flutterwave/", views.flutterwave_webhook, name="flutterwave_webhook"),

    # ── Report ───────────────────────────────────────────────────────────
    path("report-issue/", views.report_view, name="report_view"),
    path('check-sms/5sim/<str:order_id>/', views.check_sms_5sim, name='check_sms_5sim'),
    
]