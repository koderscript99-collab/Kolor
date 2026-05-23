from django.urls import path
from . import views

urlpatterns = [
    # AUTH
    path('', views.signup, name='signup'),
    path('signup/', views.signup, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # DASHBOARD
    path('home/', views.home, name='home'),
    path('success/', views.success, name='success'),

    # API (separate from normal login!)
    path('api/login/', views.login_view, name='api_login'),
    path('api/profile/', views.get_profile, name='profile'),
    path('api/profile/update/', views.update_profile, name='update_profile'),

    # FEATURES
    path('payment/', views.payment, name='payment'),
    path('report/', views.report, name='report'),
    path('transaction/', views.transaction, name='transaction'),

    # TRANSACTIONS
    path('deposit/', views.deposit, name='deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('transfer/', views.transfer, name='transfer'),
    path('buy-data/', views.buy_data, name='buy_data'),
    path('succed-data/', views.succed_data, name='succed_data'),
    path('low-balance/', views.low_balance, name='low_balance'),
    path('succed-trans/', views.succed_trans, name='succed_trans'),
    path('payment_success/', views.payment_success, name='payment_success'),
    path('report/', views.report_view, name='report'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('buy-data/', views.buy_data, name='buy_data'),
    path('market/', views.market, name='market'),
    path("webhook/flutterwave/", views.flutterwave_webhook, name="webhook"),
]