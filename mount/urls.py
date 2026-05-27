from django.urls import path
from . import views

urlpatterns = [
    # AUTH
    path('',              views.signup,      name='signup'),
    path('signup/',       views.signup,      name='signup'),
    path('login/',        views.login_view,  name='login'),
    path('logout/',       views.logout_view, name='logout'),

    # DASHBOARD
    path('home/',         views.home,        name='home'),
    path('success/',      views.success,     name='success'),

    # API
    path('api/login/',          views.api_login,      name='api_login'),
    path('api/profile/',        views.get_profile,    name='profile'),
    path('api/profile/update/', views.update_profile, name='update_profile'),

    # PAYMENT
    path('payment/',         views.payment,         name='payment'),
    path('transaction/',     views.transaction,     name='transaction'),
    path('deposit/',         views.deposit,         name='deposit'),
    path('withdraw/',        views.withdraw,        name='withdraw'),
    path('transfer/',        views.transfer,        name='transfer'),
    path('payment_success/', views.payment_success, name='payment_success'),

    # DATA — ClubKonnect
    path('buy-data/',     views.buy_data,    name='buy_data'),
    path('succed-data/',  views.succed_data, name='succed_data'),
    path('low-balance/',  views.low_balance, name='low_balance'),
    path('succed-trans/', views.succed_trans,name='succed_trans'),

    # DATA — Beewave Special Bundles
    path('buy-special-bundle/', views.buy_special_bundle, name='buy_special_bundle'),

    # SMM / MARKET
    path('market/',                   views.market,          name='market'),
    path('buy-smm/',                  views.buy_smm,         name='buy_smm'),
    path('smm/check/<int:order_id>/', views.check_smm_order, name='check_smm_order'),

    # REPORTS
    path('report/', views.report_view, name='report'),

    # WEBHOOK
    path('webhook/flutterwave/', views.flutterwave_webhook, name='webhook'),
]