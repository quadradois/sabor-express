import io
import sqlite3
import tarfile
from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.loader import MigrationLoader

from backup import nucleo
from backup.situacao import situacao_backup


@pytest.fixture
def ambiente(tmp_path, settings):
    """Banco SQLite de arquivo + mídia + pasta de backup, tudo temporário."""
    banco = tmp_path / "db.sqlite3"
    midia = tmp_path / "media"
    midia.mkdir()
    (midia / "foto.txt").write_text("foto da ficha")
    con = sqlite3.connect(banco)
    con.execute("CREATE TABLE django_migrations (app text, name text)")
    con.executemany("INSERT INTO django_migrations VALUES (?,?)",
                    [(a, n) for a, n in MigrationLoader(None, ignore_no_migrations=True).disk_migrations])
    con.execute("CREATE TABLE nucleo_registrooperacao (id integer, criado_em text)")
    con.execute("INSERT INTO nucleo_registrooperacao VALUES (1, '2026-11-10 09:00:00')")
    con.execute("CREATE TABLE dado (v text)")
    con.execute("INSERT INTO dado VALUES ('original')")
    con.commit()
    con.close()
    settings.DATABASES["default"]["NAME"] = str(banco)
    settings.MEDIA_ROOT = midia
    settings.BACKUP_DIR = tmp_path / "backups"
    return banco, midia, tmp_path / "backups"


def valores(banco):
    con = sqlite3.connect(banco)
    try:
        return [r[0] for r in con.execute("SELECT v FROM dado")]
    finally:
        con.close()


def test_backup_gera_arquivo_valido(ambiente, capsys):
    banco, midia, pasta = ambiente
    call_command("backup")
    arquivos = list(pasta.glob("sabor-express-*.tar.gz"))
    assert len(arquivos) == 1
    m = nucleo.ler_backup(arquivos[0])
    assert m["ultima_operacao"] == "2026-11-10 09:00:00"
    assert m["tabelas"] == 3
    with tarfile.open(arquivos[0]) as t:
        assert "media/foto.txt" in t.getnames()
    assert "conferido" in capsys.readouterr().out


def test_backup_destino_por_argumento(ambiente, tmp_path):
    call_command("backup", destino=str(tmp_path / "outro"))
    assert len(list((tmp_path / "outro").glob("*.tar.gz"))) == 1


def test_restauracao_devolve_os_dados(ambiente):
    banco, midia, pasta = ambiente
    arquivo = nucleo.criar_backup()
    con = sqlite3.connect(banco)
    con.execute("UPDATE dado SET v='estragado'")
    con.commit()
    con.close()
    (midia / "foto.txt").write_text("estragada")
    (midia / "nova.txt").write_text("não existia")
    call_command("restaurar", str(arquivo), confirmar=True)
    assert valores(banco) == ["original"]
    assert (midia / "foto.txt").read_text() == "foto da ficha"
    assert not (midia / "nova.txt").exists()
    seguranca = list(pasta.glob("sabor-express-antes-de-restaurar-*.tar.gz"))
    assert len(seguranca) == 1  # backup do estado anterior
    # o de segurança guarda o estado estragado
    assert nucleo.ler_backup(seguranca[0])["ultima_operacao"]


def test_restaurar_exige_confirmar(ambiente):
    banco, midia, pasta = ambiente
    arquivo = nucleo.criar_backup()
    con = sqlite3.connect(banco)
    con.execute("UPDATE dado SET v='mudou'")
    con.commit()
    con.close()
    with pytest.raises(CommandError, match="--confirmar"):
        call_command("restaurar", str(arquivo))
    assert valores(banco) == ["mudou"]
    assert not list(pasta.glob("*antes-de-restaurar*"))


def test_backup_corrompido_e_recusado(ambiente, tmp_path):
    banco, midia, pasta = ambiente
    ruim = tmp_path / "sabor-express-20260101-000000.tar.gz"
    ruim.write_bytes(b"isto nao e um backup")
    with pytest.raises(CommandError, match="recusado"):
        call_command("restaurar", str(ruim), confirmar=True)
    assert valores(banco) == ["original"]


def test_banco_corrompido_dentro_do_arquivo_e_recusado(ambiente, tmp_path):
    arquivo = nucleo.criar_backup()
    ruim = tmp_path / "ruim.tar.gz"
    with tarfile.open(arquivo) as origem, tarfile.open(ruim, "w:gz") as dest:
        for membro in origem.getmembers():
            if membro.name == "db.sqlite3":
                lixo = b"SQLite format 3\x00" + b"\xff" * 4000
                membro.size = len(lixo)
                dest.addfile(membro, io.BytesIO(lixo))
            elif membro.isfile():
                dest.addfile(membro, origem.extractfile(membro))
    with pytest.raises(nucleo.BackupErro):
        nucleo.ler_backup(ruim)


def test_backup_de_versao_mais_nova_e_recusado(ambiente, tmp_path):
    banco, midia, pasta = ambiente
    con = sqlite3.connect(banco)
    con.execute("INSERT INTO django_migrations VALUES ('nucleo', '9999_do_futuro')")
    con.commit()
    con.close()
    arquivo = nucleo.criar_backup()
    with pytest.raises(CommandError, match="mais nova"):
        call_command("restaurar", str(arquivo), confirmar=True)


def test_retencao_apaga_so_o_que_deve(ambiente):
    banco, midia, pasta = ambiente
    pasta.mkdir()
    agora = datetime(2026, 11, 12, 12, 0, 0)

    def cria(dt):
        p = pasta / f"sabor-express-{dt.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        p.write_bytes(b"x")
        return p

    recente = cria(agora - timedelta(days=3))
    limite = cria(agora - timedelta(days=13))
    out_1a = cria(datetime(2026, 9, 5, 3, 0, 0))   # mais antigo de setembro: fica
    out_1b = cria(datetime(2026, 9, 20, 3, 0, 0))  # outro de setembro: sai
    velho = cria(datetime(2025, 8, 1, 3, 0, 0))    # fora dos 12 meses: sai
    manual = pasta / "db.sqlite3.bak-antes-migracao"
    manual.write_bytes(b"manual")
    seguranca = pasta / "sabor-express-antes-de-restaurar-20240101-000000.tar.gz"
    seguranca.write_bytes(b"seg")
    estranho = pasta / "fotos-da-viagem.tar.gz"
    estranho.write_bytes(b"outra coisa")

    apagados = nucleo.aplicar_retencao(agora=agora)
    assert set(apagados) == {out_1b, velho}
    for p in (recente, limite, out_1a, manual, seguranca, estranho):
        assert p.exists()


def test_situacao_do_backup(ambiente):
    banco, midia, pasta = ambiente
    assert situacao_backup() == {**situacao_backup(), "existe": False, "atrasado": True, "quantidade": 0}
    arquivo = nucleo.criar_backup(agora=datetime(2026, 11, 11, 23, 0, 0))
    s = situacao_backup(agora=datetime(2026, 11, 12, 8, 0, 0))
    assert s["existe"] and s["quantidade"] == 1 and not s["atrasado"]
    assert s["horas_desde_ultimo"] == 9.0
    assert s["ultimo_tamanho_bytes"] == arquivo.stat().st_size
    assert situacao_backup(agora=datetime(2026, 11, 14, 0, 0, 0))["atrasado"]
