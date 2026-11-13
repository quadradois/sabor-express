"""Rotina da caixa de decisões: `uv run python manage.py rotina_diaria`.

Expira o que passou do prazo e roda os geradores (validade, estoque baixo, contas, recebimento atrasado,
consumo pendente, avisos de ajuste, sugestão de ficha). Pode rodar quantas vezes quiser: não duplica.
O agendamento (cron/systemd) é da coordenação.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from decisoes.geradores import rodar_rotina


class Command(BaseCommand):
    help = "Atualiza a caixa de decisões (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--data", help="dia de referência AAAA-MM-DD (padrão: hoje)")

    def handle(self, *args, data=None, **options):
        try:
            hoje = date.fromisoformat(data) if data else None
        except ValueError:
            raise CommandError("Data inválida (use AAAA-MM-DD).") from None
        r = rodar_rotina(hoje=hoje)
        self.stdout.write(f"Rotina de {r['hoje']:%d/%m/%Y}: {r['expiradas']} expiradas.")
        falhou = False
        for origem, g in r["geradores"].items():
            if "erro" in g:
                falhou = True
                self.stderr.write(f"  {origem}: ERRO {g['erro']}")
            else:
                self.stdout.write(f"  {origem}: {g['criadas']} novas, {g['atualizadas']} atualizadas, "
                                  f"{g['sem_efeito']} sem efeito, {g['pendentes']} pendentes")
        if falhou:
            raise CommandError("Algum gerador falhou (ver acima).")
