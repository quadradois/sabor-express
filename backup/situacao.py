"""Consulta pura: como está o backup? (para tela e agente usarem depois)"""
from datetime import datetime

from .nucleo import listar_backups


def situacao_backup(destino=None, limite_horas=26, agora=None):
    """Dicionário com o último backup, quantos existem e se está atrasado.

    `atrasado` é True se não há backup ou o último tem mais de `limite_horas` horas.
    """
    agora = agora or datetime.now()
    backups = listar_backups(destino)
    if not backups:
        return {"existe": False, "ultimo_em": None, "ultimo_arquivo": None,
                "ultimo_tamanho_bytes": None, "quantidade": 0,
                "horas_desde_ultimo": None, "atrasado": True}
    data, caminho = backups[0]
    horas = (agora - data).total_seconds() / 3600
    return {"existe": True, "ultimo_em": data, "ultimo_arquivo": caminho.name,
            "ultimo_tamanho_bytes": caminho.stat().st_size, "quantidade": len(backups),
            "horas_desde_ultimo": round(horas, 1), "atrasado": horas > limite_horas}
