from django.urls import path
from lab import views, data_views

urlpatterns = [path('datasets/',data_views.datasets,name='datasets'),
               path('datasets/<uuid:pk>/',data_views.dataset_detail,name='dataset'),
               path('results/<uuid:pk>/evaluate/',data_views.evaluation_setup,name='evaluate'),
               path('evaluations/confirm/',data_views.confirm_holdout,name='confirm_holdout'),
               path('evaluations/<uuid:pk>/',data_views.evaluation_detail,name='evaluation'),
               path("", views.home, name="home"), path("problems/new/", views.editor, name="new"),
               path("problems/<uuid:pk>/", views.editor, name="edit"),
               path("results/<uuid:pk>/", views.result, name="result"),
               path("results/<uuid:pk>/points/<int:index>/", views.point_detail, name="point"),
               path("results/<uuid:pk>/choose/", views.choose, name="choose"),
               path("results/<uuid:pk>/clone/", views.clone, name="clone")]
