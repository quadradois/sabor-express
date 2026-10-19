from .operacoes import executar


class AdminViaExecutar:
    """Mixin de ModelAdmin: o admin grava pelo núcleo (atômico e auditado)."""

    def save_model(self, request, obj, form, change):
        pass  # gravado em save_related, dentro do executar()

    def save_related(self, request, form, formsets, change):
        obj = form.instance

        def func(op):
            obj.save()
            super(AdminViaExecutar, self).save_related(request, form, formsets, change)
            self.depois_de_salvar(obj, op)
            return {"id": obj.pk}

        executar(f"salvar_{self.opts.model_name}", func, autor=request.user.username,
                 canal="web", parametros={"id": obj.pk})

    def depois_de_salvar(self, obj, op):
        pass

    def delete_model(self, request, obj):
        pk = obj.pk

        def func(op):
            obj.delete()
            return {"id": pk}

        executar(f"excluir_{self.opts.model_name}", func, autor=request.user.username,
                 canal="web", parametros={"id": pk})
