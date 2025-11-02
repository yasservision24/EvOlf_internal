# core/urls.py
from django.urls import path
from .views.dataset_views import DatasetListAPIView, DatasetExportAPIView, DatasetDownloadAPIView
from .views.elastic_search_views import ElasticSearchView

# from .views.prediction_model_views import PredictAPIView


urlpatterns = [
    path('dataset/', DatasetListAPIView.as_view(), name='dataset-list'),
    path('dataset/export', DatasetExportAPIView.as_view(), name='dataset-export'),
    path('dataset/download', DatasetDownloadAPIView.as_view(), name='dataset-download'),
    path("search/", ElasticSearchView.as_view(), name="elastic_search"),
]