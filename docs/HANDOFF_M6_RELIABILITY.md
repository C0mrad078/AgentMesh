# HANDOFF M6 — Backend Reliability

Agent: Backend Reliability (Codex 1)
Branch: `feat/v3-production-readiness`

## Entregas

- `BackupManager`: snapshot SQLite online usando `Connection.backup()`, manifesto JSON com checksum SHA-256 e resumo, cópias protegidas e retenção configurável (padrão cinco backups não protegidos).
- `RestoreManager`: valida manifesto, tamanho, checksum e compatibilidade; testa `integrity_check` e `foreign_key_check` em conexão isolada; cria snapshot online pré-restore, faz troca por `os.replace` e reconecta o `Database`, revertendo ao snapshot se o startup pós-restore falhar.
- `DiagnosticsCollector`: relatório e ZIP com os cinco arquivos contratuais. O conteúdo de tabela nunca é exportado; logs aceitam somente metadados estruturados selecionados. Segredos, prompts, conteúdo de código e valores arbitrários são omitidos/redigidos.
- `diagnose_recovery`: aponta banco ausente/corrompido, backup ausente, manifesto inválido, checksum/schema incompatível e artefatos temporários de operações interrompidas.
- Cobertura unitária/integrada para backup, retenção, restore, rollback, checksum/schema e sanitização de diagnóstico.

## Validação

```text
.venv/bin/pytest tests/python/test_reliability_core.py
.venv/bin/ruff check core/reliability tests/python/test_reliability_core.py
.venv/bin/mypy core/reliability
```

Commit pendente de autorização da janela sequencial. Não foram staged nem commitados arquivos.

## Notas de integração

- A camada de bridge (comandos diagnostics/backup/onboarding) permanece com o Lead, conforme ownership do contrato M6.
- O caminho de backup e a retenção devem ser configurados pela camada de aplicação usando diretório seguro do usuário; nunca remover diretórios de dados em upgrade/uninstall.
- O bundle não exporta prompts nem mensagens de log não estruturadas. Providers e runtime bindings devem ser fornecidos já como observações locais; a projeção final limita os campos exportados.
