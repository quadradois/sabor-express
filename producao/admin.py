from django.contrib import admin

from estoque.admin import SomenteLeitura

from .models import Producao

admin.site.register(Producao, SomenteLeitura)
