# Backup e restauração

## Como funciona

O comando `backup` guarda numa só pasta, num só arquivo por dia, uma cópia do **banco de dados** e das **fotos/arquivos** das fichas. Pode rodar com o sistema ligado: a cópia do banco é feita pelo próprio SQLite, então sai sempre inteira e consistente. Antes de dar o backup por bom, o comando confere a cópia (integridade do banco e número de tabelas). Se algo falhar, ele avisa e termina com erro.

Cada arquivo se chama `sabor-express-AAAAMMDD-HHMMSS.tar.gz`.

## Onde ficam os arquivos

Em `~/backups-sabor-express/` (padrão). Para mudar: a variável `SABOR_BACKUP_DIR` ou `--destino PASTA` no comando.

**Quanto tempo ficam:** os backups dos últimos 14 dias, mais o mais antigo de cada um dos últimos 12 meses. O resto é apagado. O comando **só apaga arquivos com o nome que ele mesmo gera**; os `.bak` feitos à mão e os backups de segurança da restauração nunca são apagados. (Ajustes: `SABOR_BACKUP_DIAS`, `SABOR_BACKUP_MESES`.)

## Fazer um backup agora

```bash
cd ~/Sabor-Express
uv run python manage.py backup
```

## Agendar todo dia

Em `deploy/` há dois arquivos de exemplo (`sabor-express-backup.service` e `.timer`, todo dia às 23h; se o computador estiver desligado, roda ao ligar). Eles **não vêm instalados**. Para ativar:

```bash
cp deploy/sabor-express-backup.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now sabor-express-backup.timer
systemctl --user list-timers | grep backup
```

Confira se o caminho do `uv` e da pasta do sistema nos arquivos estão certos para esta máquina.

## Restaurar, passo a passo

1. **Pare o sistema:** `systemctl --user stop sabor-express.service`
2. Veja o que há no backup (não altera nada):
   ```bash
   uv run python manage.py restaurar ~/backups-sabor-express/sabor-express-20261111-230000.tar.gz
   ```
   Ele mostra a data, o tamanho e a última operação registrada.
3. Se for esse mesmo, restaure:
   ```bash
   uv run python manage.py restaurar ~/backups-sabor-express/sabor-express-20261111-230000.tar.gz --confirmar
   ```
   Antes de trocar qualquer coisa, ele faz um **backup de segurança** do estado atual (`sabor-express-antes-de-restaurar-...`). Assim dá para voltar atrás.
4. **Ligue o sistema:** `systemctl --user start sabor-express.service`

O comando recusa arquivos estragados e backups feitos por uma versão **mais nova** do sistema que a instalada. **O serviço precisa estar parado durante a restauração**, senão ele pode escrever no banco enquanto ele é trocado.

## Copie para fora do computador

Backup na mesma máquina não protege de o computador pifar, ser roubado ou pegar fogo. **Copie a pasta `~/backups-sabor-express/` de vez em quando para um pendrive, HD externo ou nuvem.** Isso **ainda é manual**: o sistema não faz essa cópia sozinho.

## Para programadores

- Código: app `backup/` (`nucleo.py`, `situacao.py`). `situacao_backup()` devolve último backup, tamanho, quantidade e se está atrasado, para uma tela/agente futuros.
- Testes: `tests/test_backup.py`.
