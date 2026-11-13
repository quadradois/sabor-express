from django.contrib import admin

from estoque.admin import SomenteLeitura

from .models import Fritura, Producao

admin.site.register(Producao, SomenteLeitura)
admin.site.register(Fritura, SomenteLeitura)
