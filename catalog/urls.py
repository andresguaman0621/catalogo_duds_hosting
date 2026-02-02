from django.urls import path
from . import views

urlpatterns = [
    path('logout/', views.user_logout, name='logout'),
    path('refresh/', views.refresh_data, name='refresh_data'),
    path('', views.select_category, name='select_category'),
    path('select_category/', views.select_category, name='select_category'),
    path('select_size/<str:category>/', views.select_size, name='select_size'),
    path('generate_pdfs/<str:category>/<str:sizes>/', views.generate_pdfs, name='generate_pdfs'),
    # descarga individual
    path('download_pdf/<str:category>/<str:size>/', views.download_pdf, name='download_pdf'),
]