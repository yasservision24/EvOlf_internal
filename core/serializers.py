# core/serializers.py
from rest_framework import serializers
from .models import EvOlf

class EvOlfSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvOlf
        # include fields you want to expose; here exposing all for simplicity
        fields = '__all__'
