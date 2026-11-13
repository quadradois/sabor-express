from django.apps import AppConfig


class DecisoesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'decisoes'

    def ready(self):
        from nucleo.operacoes import depois_de_gravar

        from .geradores import atualizar_caixa

        depois_de_gravar(atualizar_caixa)
