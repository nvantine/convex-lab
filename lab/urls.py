from django.urls import path
from lab import views, data_views, comparison_views

urlpatterns = [path("compare/",comparison_views.compare,name="compare"),path('fetches/<uuid:pk>/',data_views.fetch_progress,name='fetch_progress'),
               path('fetches/<uuid:pk>/batch/',data_views.fetch_batch,name='fetch_batch'),
               path('fetches/<uuid:pk>/action/',data_views.fetch_action,name='fetch_action'),
               path('datasets/',data_views.datasets,name='datasets'),
               path('datasets/<uuid:pk>/',data_views.dataset_detail,name='dataset'),
               path('results/<uuid:pk>/evaluate/',data_views.evaluation_setup,name='evaluate'),
               path('evaluations/confirm/',data_views.confirm_holdout,name='confirm_holdout'),
               path('evaluations/<uuid:pk>/',data_views.evaluation_detail,name='evaluation'),
               path('evaluations/<uuid:pk>/rebalances/<int:index>/',data_views.rebalance_detail,name='rebalance'),
               path("", views.home, name="home"), path("problems/new/", views.editor, name="new"),
               path("problems/<uuid:pk>/", views.editor, name="edit"),
               path("results/<uuid:pk>/", views.result, name="result"),
               path("results/<uuid:pk>/points/<int:index>/", views.point_detail, name="point"),
               path("results/<uuid:pk>/choose/", views.choose, name="choose"),
               path("results/<uuid:pk>/clone/", views.clone, name="clone")]
