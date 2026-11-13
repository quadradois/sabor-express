from django.db import migrations

# indireta = gasto da produção (comparado com o indireto de referência por salgado)
CATEGORIAS = [("Mão de obra", True), ("Energia", True), ("Gás", True), ("Diária", True), ("Internet", False),
              ("Impostos/MEI", False), ("Taxas", False), ("Outras", False)]


def criar(apps, schema_editor):
    Categoria = apps.get_model("financeiro", "CategoriaDespesa")
    for ordem, (nome, indireta) in enumerate(CATEGORIAS, 1):
        Categoria.objects.get_or_create(nome=nome, defaults={"indireta": indireta, "ordem": ordem})


class Migration(migrations.Migration):

    dependencies = [("financeiro", "0004_despesas")]

    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
