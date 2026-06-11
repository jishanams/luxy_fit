from django.urls import path
from . import views

urlpatterns = [
    path('health', views.health, name='health'),
    path('product', views.product_detail, name='product_detail'),
    path('try-on', views.try_on, name='try_on'),
    path('try-on/status/<str:job_id>', views.try_on_status, name='try_on_status'),
]
