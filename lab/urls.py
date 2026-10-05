from django.urls import path
from lab import views

urlpatterns = [path("", views.home, name="home"), path("problems/new/", views.editor, name="new"),
               path("problems/<uuid:pk>/", views.editor, name="edit"),
               path("results/<uuid:pk>/", views.result, name="result"),
               path("results/<uuid:pk>/points/<int:index>/", views.point_detail, name="point"),
               path("results/<uuid:pk>/choose/", views.choose, name="choose"),
               path("results/<uuid:pk>/clone/", views.clone, name="clone")]
