# from django_elasticsearch_dsl import Document, Index, fields
# from django_elasticsearch_dsl.registries import registry
# from .models import EvOlf

# # Define index
# evolf_index = Index('evolf_index')
# evolf_index.settings(number_of_shards=1, number_of_replicas=0)

# @registry.register_document
# class EvolfDocument(Document):
#     # You can declare only the fields you want custom analyzers for:
#     Receptor = fields.TextField(analyzer='standard')
#     Ligand = fields.TextField(analyzer='standard')
#     Species = fields.TextField(analyzer='standard')
#     Class = fields.TextField(analyzer='standard')

#     class Index:
#         name = 'evolf_index'

#     class Django:
#         model = EvOlf
#         fields = [
#             'EvOlf_ID',
#             'Receptor_ID',
#             'UniProt_ID',
#             'SMILES',
#             'ChEMBL_ID',
#             'CID',
#             'Ensembl_ID',
#         ]
