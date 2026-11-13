"""Backup e restauração: criar, verificar, aplicar retenção e restaurar.

Cada backup é um único arquivo .tar.gz com: o banco (cópia consistente feita
pela API de backup do sqlite3), a pasta de mídia e um manifesto.json.
"""
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db.migrations.loader import MigrationLoader

PREFIXO = "sabor-express-"
PREFIXO_SEGURANCA = "sabor-express-antes-de-restaurar-"
PADRAO = re.compile(r"^sabor-express-(\d{8})-(\d{6})\.tar\.gz$")
PADRAO_SEGURANCA = re.compile(r"^sabor-express-antes-de-restaurar-(\d{8})-(\d{6})\.tar\.gz$")
FORMATO = "%Y%m%d-%H%M%S"


class BackupErro(Exception):
    pass


def pasta_backup(destino=None):
    return Path(destino or settings.BACKUP_DIR).expanduser()


def data_do_nome(nome):
    """Data de um arquivo gerado por este comando, ou None se não for um."""
    m = PADRAO.match(nome)
    return datetime.strptime(m.group(1) + "-" + m.group(2), FORMATO) if m else None


def listar_backups(destino=None):
    """[(data, caminho)] dos backups diários, do mais novo ao mais antigo."""
    pasta = pasta_backup(destino)
    if not pasta.is_dir():
        return []
    achados = [(data_do_nome(p.name), p) for p in pasta.iterdir() if p.is_file()]
    return sorted([(d, p) for d, p in achados if d], key=lambda x: x[0], reverse=True)


def verificar_banco(caminho):
    """Confere um SQLite: integrity_check == ok e quantas tabelas tem."""
    try:
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        try:
            resultado = con.execute("PRAGMA integrity_check").fetchall()
            tabelas = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as e:
        raise BackupErro(f"banco ilegível: {e}")
    if resultado != [("ok",)]:
        raise BackupErro("o banco falhou na verificação de integridade")
    if tabelas == 0:
        raise BackupErro("o banco está vazio (nenhuma tabela)")
    return tabelas


def _migracoes_do_banco(caminho):
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return sorted(f"{a}.{n}" for a, n in con.execute("SELECT app, name FROM django_migrations"))
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _ultima_operacao(caminho):
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return con.execute("SELECT max(criado_em) FROM nucleo_registrooperacao").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _copiar_banco(origem, destino):
    """Cópia consistente com o sistema no ar (API de backup do sqlite3)."""
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _escrever_arquivo(destino_final, banco_copia, midia, manifesto):
    parcial = destino_final.with_name(destino_final.name + ".parcial")
    try:
        with tarfile.open(parcial, "w:gz") as tar:
            tar.add(banco_copia, arcname="db.sqlite3")
            if midia.is_dir():
                tar.add(midia, arcname="media")
            dados = json.dumps(manifesto, ensure_ascii=False, indent=1).encode()
            info = tarfile.TarInfo("manifesto.json")
            info.size = len(dados)
            info.mtime = int(datetime.now().timestamp())
            tar.addfile(info, io.BytesIO(dados))
        os.replace(parcial, destino_final)
    finally:
        parcial.unlink(missing_ok=True)


def criar_backup(destino=None, prefixo=PREFIXO, agora=None, banco=None, midia=None):
    """Gera o backup, verifica a cópia e devolve o caminho do arquivo."""
    agora = agora or datetime.now()
    banco = Path(banco or settings.DATABASES["default"]["NAME"])
    midia = Path(midia or settings.MEDIA_ROOT)
    pasta = pasta_backup(destino)
    if not banco.is_file():
        raise BackupErro(f"banco não encontrado: {banco}")
    pasta.mkdir(parents=True, exist_ok=True)
    final = pasta / f"{prefixo}{agora.strftime(FORMATO)}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="sabor-backup-") as tmp:
        copia = Path(tmp) / "db.sqlite3"
        _copiar_banco(banco, copia)
        tabelas = verificar_banco(copia)
        manifesto = {
            "formato": 1,
            "criado_em": agora.isoformat(timespec="seconds"),
            "tabelas": tabelas,
            "migracoes": _migracoes_do_banco(copia),
            "ultima_operacao": _ultima_operacao(copia),
        }
        _escrever_arquivo(final, copia, midia, manifesto)
    try:
        ler_backup(final)
    except BackupErro:
        final.unlink(missing_ok=True)
        raise
    return final


def _extrair(arquivo, pasta):
    try:
        with tarfile.open(arquivo, "r:gz") as tar:
            nomes = tar.getnames()
            if "db.sqlite3" not in nomes or "manifesto.json" not in nomes:
                raise BackupErro("o arquivo não parece um backup do Sabor Express")
            tar.extractall(pasta, filter="data")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise BackupErro(f"arquivo de backup ilegível: {e}")


def ler_backup(arquivo):
    """Confere o arquivo e devolve o manifesto (com tamanho). Levanta BackupErro se ruim."""
    arquivo = Path(arquivo)
    if not arquivo.is_file():
        raise BackupErro(f"arquivo não encontrado: {arquivo}")
    with tempfile.TemporaryDirectory(prefix="sabor-confere-") as tmp:
        _extrair(arquivo, tmp)
        verificar_banco(Path(tmp) / "db.sqlite3")
        manifesto = json.loads((Path(tmp) / "manifesto.json").read_text())
    manifesto["tamanho_bytes"] = arquivo.stat().st_size
    return manifesto


def migracoes_desconhecidas(manifesto):
    """Migrações do backup que o código atual não conhece (backup mais novo que o código)."""
    conhecidas = {f"{a}.{n}" for a, n in MigrationLoader(None, ignore_no_migrations=True).disk_migrations}
    return [m for m in manifesto.get("migracoes", []) if m not in conhecidas]


def aplicar_retencao(destino=None, diarios=None, meses=None, agora=None):
    """Apaga backups diários antigos. Só toca em arquivos com o nome gerado pelo comando.

    Fica: tudo dos últimos `diarios` dias + o mais antigo de cada um dos últimos `meses` meses.
    """
    diarios = settings.BACKUP_RETENCAO_DIAS if diarios is None else diarios
    meses = settings.BACKUP_RETENCAO_MESES if meses is None else meses
    agora = agora or datetime.now()
    limite = agora - timedelta(days=diarios)
    indice_agora = agora.year * 12 + agora.month
    existentes = listar_backups(destino)
    primeiro_do_mes = {}
    for data, caminho in existentes:  # do mais novo ao mais antigo: o último gravado é o mais antigo
        primeiro_do_mes[(data.year, data.month)] = caminho
    apagados = []
    for data, caminho in existentes:
        if data >= limite:
            continue
        idade_meses = indice_agora - (data.year * 12 + data.month)
        if idade_meses < meses and primeiro_do_mes[(data.year, data.month)] == caminho:
            continue
        caminho.unlink()
        apagados.append(caminho)
    return apagados


def restaurar(arquivo, destino=None, banco=None, midia=None):
    """Troca banco e mídia pelo conteúdo do backup. Faz antes um backup de segurança.

    O serviço precisa estar parado. Devolve o caminho do backup de segurança.
    """
    banco = Path(banco or settings.DATABASES["default"]["NAME"])
    midia = Path(midia or settings.MEDIA_ROOT)
    manifesto = ler_backup(arquivo)
    desconhecidas = migracoes_desconhecidas(manifesto)
    if desconhecidas:
        raise BackupErro("este backup é de uma versão mais nova do sistema "
                         f"({len(desconhecidas)} migrações desconhecidas, ex.: {desconhecidas[0]}); atualize o código antes")
    seguranca = criar_backup(destino, prefixo=PREFIXO_SEGURANCA, banco=banco, midia=midia)
    with tempfile.TemporaryDirectory(prefix="sabor-restaura-", dir=banco.parent) as tmp:
        _extrair(arquivo, tmp)
        novo_banco = Path(tmp) / "db.sqlite3"
        for sufixo in ("-wal", "-shm", "-journal"):
            Path(str(banco) + sufixo).unlink(missing_ok=True)
        os.replace(novo_banco, banco)
        velha = Path(tmp) / "midia-antiga"
        if midia.exists():
            os.replace(midia, velha)
        nova_midia = Path(tmp) / "media"
        if nova_midia.is_dir():
            shutil.move(str(nova_midia), str(midia))
        else:
            midia.mkdir(parents=True, exist_ok=True)
    return seguranca
