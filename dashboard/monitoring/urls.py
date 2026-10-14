from django.urls import path

from . import views

app_name = "monitoring"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("apps/<slug:code>/", views.application_detail, name="application_detail"),
]
