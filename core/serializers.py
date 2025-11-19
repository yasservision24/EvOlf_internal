# core/serializers.py
from rest_framework import serializers
from .models import EvOlf

class EvOlfSerializer(serializers.ModelSerializer):
    
    evolfId = serializers.CharField(source='EvOlf_ID')
    receptor = serializers.CharField(source='Receptor')
    species = serializers.CharField(source='Species')
    class_field = serializers.CharField(source='Class')
    ligand = serializers.CharField(source='Ligand')
    mutation = serializers.CharField(source='Mutation')
    chemblId = serializers.CharField(source='ChEMBL_ID')
    uniprotId = serializers.CharField(source='UniProt_ID')
    cid = serializers.CharField(source='CID')

    class Meta:
        model = EvOlf
        # include fields you want to expose; here exposing all for simplicity
        fields = [
            'id', 'evolfId', 'receptor', 'species', 'class_field',
            'ligand', 'mutation', 'chemblId', 'uniprotId', 'cid'
        ]
