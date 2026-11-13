from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from backup import nucleo
from backup.management.commands.backup import tamanho


class Command(BaseCommand):
    help = ("Restaura um backup (banco e mídia). PARE o serviço antes. "
            "Sem --confirmar só mostra o que seria restaurado.")

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--confirmar", action="store_true", help="de fato restaura")
        parser.add_argument("--destino", help="pasta do backup de segurança (padrão: BACKUP_DIR)")

    def handle(self, *args, **o):
        try:
            m = nucleo.ler_backup(o["arquivo"])
        except nucleo.BackupErro as e:
            raise CommandError(f"Arquivo recusado: {e}")
        criado = datetime.fromisoformat(m["criado_em"]).strftime("%d/%m/%Y %H:%M")
        self.stdout.write(f"Backup de {criado} — {tamanho(m['tamanho_bytes'])}")
        self.stdout.write(f"Última operação registrada nele: {m.get('ultima_operacao') or 'nenhuma'}")
        if not o["confirmar"]:
            raise CommandError("Nada foi alterado. Confira acima e rode de novo com --confirmar "
                               "(com o serviço parado).")
        try:
            seguranca = nucleo.restaurar(o["arquivo"], o["destino"])
        except (nucleo.BackupErro, OSError) as e:
            raise CommandError(f"Restauração RECUSADA/FALHOU: {e}")
        self.stdout.write(self.style.SUCCESS(
            f"Restaurado. Backup do estado anterior guardado em: {seguranca}"))
        self.stdout.write("Pode ligar o serviço de novo.")
