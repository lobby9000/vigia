from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Vigia back-office"
admin.site.site_title = "Vigia"
admin.site.index_title = "Applications and incidents"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only, protected by CSRF
    path("", include("monitoring.urls")),
]
