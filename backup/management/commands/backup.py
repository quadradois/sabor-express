from django.core.management.base import BaseCommand, CommandError

from backup import nucleo


def tamanho(b):
    return f"{b / 1024 / 1024:.1f} MB" if b >= 1024 * 1024 else f"{b / 1024:.0f} KB"


class Command(BaseCommand):
    help = "Faz o backup do banco e da mídia num arquivo datado e apaga os backups antigos."

    def add_arguments(self, parser):
        parser.add_argument("--destino", help="pasta dos backups (padrão: BACKUP_DIR)")
        parser.add_argument("--dias", type=int, help="quantos dias seguidos manter (padrão 14)")
        parser.add_argument("--meses", type=int, help="quantos meses manter um por mês (padrão 12)")

    def handle(self, *args, **o):
        try:
            arquivo = nucleo.criar_backup(o["destino"])
        except (nucleo.BackupErro, OSError) as e:
            raise CommandError(f"Backup FALHOU: {e}")
        self.stdout.write(self.style.SUCCESS(
            f"Backup feito e conferido: {arquivo} ({tamanho(arquivo.stat().st_size)})"))
        try:
            apagados = nucleo.aplicar_retencao(o["destino"], o["dias"], o["meses"])
        except OSError as e:
            raise CommandError(f"Backup feito, mas a limpeza dos antigos falhou: {e}")
        if apagados:
            self.stdout.write(f"Backups antigos apagados: {len(apagados)}")
