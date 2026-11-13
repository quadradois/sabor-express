"""Vendas (balcão e atacado), encomendas com reserva de estoque e as apresentações com preço (Plano 6).

Preço, fator e custo ficam gravados na linha (RN-30): mudar a tabela depois não muda a venda.
Nada é apagado: venda e encomenda se cancelam com motivo; reserva se libera ou se baixa.
"""

from django.db import models

from estoque.models import ESTADOS, FORMAS

TABELAS = [("varejo", "Varejo"), ("atacado", "Atacado")]
CONDICOES = [("a_vista", "À vista"), ("a_prazo", "A prazo")]
DESTINOS = [("perda", "Perda"), ("estoque", "Volta ao estoque")]
MODOS = [("retirada", "Retirada"), ("entrega", "Entrega")]


class Apresentacao(models.Model):
    """Como o produto é vendido (RF-CAD-04): unidade, caixa ou cento, em uma forma e conservação, com preço.

    Cada tamanho já é um produto (design §6.3.7); a apresentação diz quantas unidades vão, de que jeito
    (cru congelado, frito fresco...) e quanto custa no varejo e no atacado."""

    produto = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT, related_name="apresentacoes",
                                limit_choices_to={"tipo": "produto"})
    nome = models.CharField(max_length=60)  # "unidade", "caixa com 25", "cento"
    forma = models.CharField(max_length=10, choices=FORMAS)
    estado = models.CharField(max_length=20, choices=ESTADOS)
    unidades = models.PositiveIntegerField()  # unidades físicas do produto por apresentação (RN-29)
    embalagem = models.ForeignKey("cadastros.Item", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+", limit_choices_to={"tipo": "embalagem"})
    embalagens = models.DecimalField(max_digits=14, decimal_places=3, default=0)  # por apresentação, unidade base
    preco_varejo = models.DecimalField(max_digits=12, decimal_places=2)
    preco_atacado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "apresentações"
        constraints = [models.UniqueConstraint(fields=["produto", "nome"], name="apresentacao_unica_por_produto")]

    def __str__(self):
        return f"{self.produto} — {self.nome} ({self.forma}, {self.estado})"


class CanalVenda(models.Model):
    """Por onde a venda entra e a taxa que fica no caminho (Plano 8, estudo de preço): balcão em dinheiro ou
    pix sem taxa, cartão com a taxa da maquininha, plataformas no futuro. `taxa_pct` vazia = não informada."""

    nome = models.CharField(max_length=60, unique=True)
    taxa_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # % do preço
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "canal de venda"
        verbose_name_plural = "canais de venda"

    def __str__(self):
        return self.nome


class Venda(models.Model):
    """Venda concluída (balcão, atacado ou encomenda entregue). Situação: concluida | cancelada."""

    cliente = models.ForeignKey("cadastros.Cliente", null=True, blank=True, on_delete=models.PROTECT)
    data = models.DateField()
    tabela = models.CharField(max_length=10, choices=TABELAS, default="varejo")
    condicao = models.CharField(max_length=10, choices=CONDICOES)
    forma_pagamento = models.CharField(max_length=30, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    # quanto entrou na hora (à vista; na encomenda, o que foi pago na entrega, fora o sinal)
    recebido_na_hora = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    custo = models.DecimalField(max_digits=12, decimal_places=2)  # custo dos lotes baixados (RN-30)
    encomenda = models.OneToOneField("Encomenda", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="venda")
    situacao = models.CharField(max_length=10, default="concluida")
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    cancelamento_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                              on_delete=models.PROTECT, related_name="+")
    motivo_cancelamento = models.CharField(max_length=200, blank=True)
    destino = models.CharField(max_length=10, choices=DESTINOS, blank=True)  # das unidades no cancelamento
    valor_devolvido = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # anotação (FL-09 P3)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Venda {self.id}"


class LinhaVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, related_name="linhas")
    apresentacao = models.ForeignKey(Apresentacao, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField()  # de apresentações
    unidades_por = models.PositiveIntegerField()  # fator gravado (RN-30)
    preco_tabela = models.DecimalField(max_digits=12, decimal_places=2)  # preço original (RF-VEN-01)
    preco = models.DecimalField(max_digits=12, decimal_places=2)  # praticado, por apresentação
    total = models.DecimalField(max_digits=12, decimal_places=2)
    custo = models.DecimalField(max_digits=12, decimal_places=2)
    # [{"lote_id", "item_id", "estado", "quantidade", "custo"}] — o que saiu de cada lote (produto e embalagem)
    baixas = models.JSONField(default=list)
    # Plano 9: o atendente indicou de qual lote pegou (sem isso, FEFO automático)
    lotes_indicados = models.BooleanField(default=False)
    # porções que vencem antes e ficaram para trás: [{"lote_id", "estado", "unidades", "validade"}]
    deixados = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]


class Encomenda(models.Model):
    """Pedido com data (RF-VEN-05). Situação gravada: aberta | entregue | cancelada; "pronta" é derivada
    (tudo reservado). Reserva ao ser criada (RN-35); a entrega vira venda uma única vez (RF-VEN-08)."""

    cliente = models.ForeignKey("cadastros.Cliente", on_delete=models.PROTECT)
    entrega_data = models.DateField()
    entrega_hora = models.TimeField(null=True, blank=True)  # vazia = hora não combinada
    modo = models.CharField(max_length=10, choices=MODOS, default="retirada")
    observacao = models.CharField(max_length=200, blank=True)
    tabela = models.CharField(max_length=10, choices=TABELAS, default="varejo")
    total = models.DecimalField(max_digits=12, decimal_places=2)
    sinal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sinal_forma = models.CharField(max_length=30, blank=True)
    situacao = models.CharField(max_length=10, default="aberta")
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    fim_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    motivo_cancelamento = models.CharField(max_length=200, blank=True)
    sinal_devolvido = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # anotação
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Encomenda {self.id} — {self.cliente}"


class ItemEncomenda(models.Model):
    encomenda = models.ForeignKey(Encomenda, on_delete=models.PROTECT, related_name="itens")
    apresentacao = models.ForeignKey(Apresentacao, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField()
    unidades_por = models.PositiveIntegerField()
    preco_tabela = models.DecimalField(max_digits=12, decimal_places=2)
    preco = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    @property
    def unidades(self):
        return self.quantidade * self.unidades_por


class Reserva(models.Model):
    """Unidades de uma porção (lote + conservação) separadas para uma encomenda (RN-35).

    Situação: ativa (conta no reservado, RN-03) | baixada (virou saída na entrega) | liberada
    (cancelamento, lote vencido ou descartado). Não gera movimento: o saldo só muda na entrega."""

    item_encomenda = models.ForeignKey(ItemEncomenda, on_delete=models.PROTECT, related_name="reservas")
    lote = models.ForeignKey("estoque.Lote", on_delete=models.PROTECT, related_name="reservas")
    estado = models.CharField(max_length=20, choices=ESTADOS)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)
    situacao = models.CharField(max_length=10, default="ativa")
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    fim_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    motivo = models.CharField(max_length=200, blank=True)  # por que foi liberada
    criado_em = models.DateTimeField(auto_now_add=True)
