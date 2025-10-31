from django.urls import path
from .views import ElasticSearchView

urlpatterns = [
    path("search/", ElasticSearchView.as_view(), name="elastic_search"),
]
