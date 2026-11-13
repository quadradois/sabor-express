from django.db import models
from django.db.models import Q


class Decisao(models.Model):
    """Item da caixa de decisões: o que espera o "ok" do dono, sem pressa.

    Com `operacao`, aprovar executa a operação pelo núcleo com a `chave` da decisão (uma única vez).
    Sem `operacao`, é um aviso: aprovar é "ciente". Nada é apagado: a decisão só muda de situação.

    `assunto` identifica a situação que gerou o item (ex.: "lote_vencido:12:congelado"). Só pode haver uma
    decisão `vigente` por assunto: enquanto a situação existir, a rotina não cria outra, mesmo que o dono já
    tenha recusado ou dado ciência. Quando a situação deixa de existir, a decisão deixa de ser vigente (e, se
    ainda estava pendente, fica "sem efeito"); se voltar a acontecer, nasce uma decisão nova.
    """
    SITUACOES = [("pendente", "Pendente"), ("aprovada", "Aprovada"), ("recusada", "Recusada"),
                 ("expirada", "Expirada"), ("sem_efeito", "Sem efeito")]

    origem = models.CharField(max_length=40)  # gerador da rotina (ex.: "lotes_vencidos") ou quem criou
    assunto = models.CharField(max_length=200)
    vigente = models.BooleanField(default=True)
    texto = models.TextField()  # o que aconteceu e o que fazer, em frases faláveis
    detalhes = models.JSONField(default=dict, blank=True)  # os números por trás do texto
    operacao = models.CharField(max_length=100, blank=True)  # vazio = aviso (só ciência)
    parametros = models.JSONField(null=True, blank=True)
    situacao = models.CharField(max_length=10, choices=SITUACOES, default="pendente")
    chave = models.CharField(max_length=200, unique=True)  # chave de idempotência da execução
    criada_em = models.DateTimeField(auto_now_add=True)
    criada_por = models.CharField(max_length=100)
    canal = models.CharField(max_length=20)
    criacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT, related_name="+")
    expira_em = models.DateTimeField(null=True, blank=True)  # vazio = vale enquanto a situação existir
    decidida_em = models.DateTimeField(null=True, blank=True)
    decidida_por = models.CharField(max_length=100, blank=True)
    motivo = models.TextField(blank=True)  # da recusa, ou por que ficou sem efeito
    decisao_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    registro = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")  # a operação executada ao aprovar
    resultado = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "decisão"
        verbose_name_plural = "decisões"
        constraints = [models.UniqueConstraint(fields=["assunto"], condition=Q(vigente=True),
                                               name="decisao_vigente_unica_por_assunto")]
        indexes = [models.Index(fields=["situacao", "origem"])]

    @property
    def tipo(self):
        return "decisao" if self.operacao else "aviso"

    def __str__(self):
        return f"#{self.id} {self.origem} ({self.situacao})"
