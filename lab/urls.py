from django.urls import path
from lab import views

urlpatterns = [path("", views.home, name="home"), path("problems/new/", views.editor, name="new"),
               path("problems/<uuid:pk>/", views.editor, name="edit"),
               path("results/<uuid:pk>/", views.result, name="result"),
               path("results/<uuid:pk>/clone/", views.clone, name="clone")]
