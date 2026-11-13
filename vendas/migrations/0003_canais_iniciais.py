from django.db import migrations

# taxa vazia = não informada (o estudo de preço avisa; nunca vira zero)
CANAIS = [("Balcão — dinheiro", "0"), ("Balcão — pix", "0"), ("Cartão de débito", None),
          ("Cartão de crédito", None)]


def criar(apps, schema_editor):
    Canal = apps.get_model("vendas", "CanalVenda")
    for ordem, (nome, taxa) in enumerate(CANAIS, 1):
        Canal.objects.get_or_create(nome=nome, defaults={"taxa_pct": taxa, "ordem": ordem})


class Migration(migrations.Migration):

    dependencies = [("vendas", "0002_canais_de_venda")]

    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
