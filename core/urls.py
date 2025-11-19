# core/urls.py
from django.urls import path
from .views.dataset_views import DatasetListAPIView, DatasetExportAPIView, DatasetDownloadAPIView,FetchDatasetDetails
from .views.elastic_search_views import ElasticSearchView
# from core.views.structure_views import FetchStructureFilesAPIView
from core.views.structure_views import FetchLocalStructureAPIView
from django.conf import settings
from django.conf.urls.static import static
from core.views.dataset_views import FetchDatasetDetails, DownloadByEvolfId
from core.views.prediction_views import SmilesPredictionAPIView
from core.views.job_status_views import JobStatusAPIView,DownloadOutputAPIView



urlpatterns = [
    path('dataset/', DatasetListAPIView.as_view(), name='dataset-list'),
    path('dataset/export', DatasetExportAPIView.as_view(), name='dataset-export'),
    path('dataset/download', DatasetDownloadAPIView.as_view(), name='dataset-download'),
    path("search/", ElasticSearchView.as_view(), name="elastic_search"),
    # path("fetch-structures/<str:evolf_id>/", FetchStructureFilesAPIView.as_view(), name="fetch-structures"),

    #path("structures/<str:evolf_id>/", FetchLocalStructureAPIView.as_view(), name="fetch-local-structure"),
    # path("dataset/export/<str:evolfId>/", DownloadDatasetByEvolf.as_view(), name="download-dataset-evolf"),


    path('dataset/details/<str:evolfId>/', FetchDatasetDetails.as_view(), name='fetch_dataset_details'),
    path('dataset/export/<str:evolfId>/', DownloadByEvolfId.as_view(), name='download_by_evolf'),

    path("predict/smiles/", SmilesPredictionAPIView.as_view()),
    # path("predict/csv/", CSVPredictionAPIView.as_view()),
    path("predict/job/<str:job_id>/", JobStatusAPIView.as_view(), name="job-status"),
    path("predict/download/<str:job_id>/", DownloadOutputAPIView.as_view(), name="job-download"),
]

