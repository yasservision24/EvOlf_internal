# core/urls.py
from django.urls import path
from .views.dataset_views import DatasetListAPIView, DatasetExportAPIView, DatasetDownloadAPIView
from .views.elastic_search_views import ElasticSearchView
from core.views.structure import FetchStructureFilesAPIView

# from .views.prediction_model_views import PredictAPIView


urlpatterns = [
    path('dataset/', DatasetListAPIView.as_view(), name='dataset-list'),
    path('dataset/export', DatasetExportAPIView.as_view(), name='dataset-export'),
    path('dataset/download', DatasetDownloadAPIView.as_view(), name='dataset-download'),
    path("search/", ElasticSearchView.as_view(), name="elastic_search"),
    path("fetch-structures/<str:evolf_id>/", FetchStructureFilesAPIView.as_view(), name="fetch-structures"),
    path("dataset/export/<str:evolfId>/", DownloadDatasetByEvolf.as_view(), name="download-dataset-evolf"),
]