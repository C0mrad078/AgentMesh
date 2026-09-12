# Processo de release

## Versionamento

SemVer (`MAJOR.MINOR.PATCH`), versão única compartilhada entre
`desktop/package.json`, `desktop/src-tauri/Cargo.toml` e `pyproject.toml`.
Incrementa:

- `MAJOR` — mudança que quebra compatibilidade de dados existentes (formato
  de banco, formato de configuração) sem migração automática.
- `MINOR` — nova funcionalidade compatível com versões anteriores (as
  migrations de banco cobrem qualquer mudança de schema).
- `PATCH` — correção de bug, sem mudança de comportamento observável além
  do bug corrigido.

## Pré-condições para qualquer release

Nenhuma release é cortada sem que, na mesma revisão:

1. O quality gate completo passe (`./scripts/test.sh`) — Python (`ruff` +
   `mypy` + `pytest`), frontend (`typecheck` + `lint` + `test` + `build`).
2. `CHANGELOG.md` tenha uma seção nova para a versão, escrita a partir dos
   commits reais desde a última tag (nunca uma lista genérica).
3. Nenhum item da seção "Bugs conhecidos" do relatório de qualidade mais
   recente tenha severidade crítica ou alta em aberto.
4. A auditoria de segurança (`gitleaks`, `pip-audit`, `npm audit`) tenha
   rodado no CI para o commit da release — ver limitação abaixo.

**Não existe release automática por política.** Um push de tag não
publica nada sozinho sem uma aprovação humana explícita — isso é
deliberado: empacotamento de desktop envolve assinatura de código com
certificados que só uma pessoa autorizada deve poder acionar.

## Passo a passo

```bash
# 1. Da main, com o quality gate verde:
./scripts/test.sh

# 2. Atualizar a versão nos três lugares e o CHANGELOG.md
#    (desktop/package.json, desktop/src-tauri/Cargo.toml, pyproject.toml)

# 3. Commit da mudança de versão
git commit -am "chore(release): v<versão>"

# 4. Tag anotada
git tag -a "v<versão>" -m "v<versão>"
git push origin main --tags
```

A tag `vX.Y.Z` no GitHub Actions dispara (quando configurado — ver
limitação abaixo) o job de build/empacotamento descrito em
`docs/BUILD.md`, que:

5. Roda o quality gate completo mais uma vez no runner de CI (não confia
   apenas no gate local).
6. Compila o sidecar Python (PyInstaller) por plataforma.
7. Roda `tauri build` para macOS e Windows, assinando e notarizando com os
   secrets do repositório (certificado Apple/Windows).
8. Publica os artefatos assinados como GitHub Release, junto do
   `latest.json` do Updater assinado com a chave Ed25519 do projeto.

## O que é real e o que é `UNVERIFIED EXTERNAL DEPENDENCY` neste momento

| Etapa | Status |
|---|---|
| Quality gate local (passo 1) | Real, executado repetidamente neste trabalho |
| `CHANGELOG.md` por versão | Real, mantido neste repositório |
| CI rodando em push/PR (lint/test/build multiplataforma) | Workflow escrito e validado sintaticamente; **nunca executado** neste ambiente (sem runner do GitHub Actions) — `UNVERIFIED EXTERNAL DEPENDENCY` |
| Job de release disparado por tag, build assinado | **Não implementado ainda** — o workflow atual (`ci.yml`) cobre verificação contínua, não o pipeline de release/assinatura descrito em `docs/BUILD.md`; escrever esse workflow (`release.yml`) fica como trabalho futuro documentado, não fingido como pronto |
| Assinatura/notarização macOS e Windows | `UNVERIFIED EXTERNAL DEPENDENCY` — sem certificados neste ambiente, ver `docs/BUILD.md` |
| Publicação do Updater (`latest.json` assinado) | `UNVERIFIED EXTERNAL DEPENDENCY` — chave Ed25519 do Updater não gerada |

## Rollback de uma release

Se um bug crítico for descoberto após publicar:

1. Nunca editar ou apagar a tag/release publicada (quebra a cadeia de
   auditoria e o Updater de usuários que já atualizaram).
2. Cortar um `PATCH` novo com a correção, seguindo o processo normal acima.
3. Se o bug envolver corrupção de dados, o caminho de recuperação do
   usuário é a função de restauração de backup já existente
   (`core/database/backup.py`, exposta em Configurações → Dados) — nunca
   uma migração de "downgrade" de schema, que não existe por design (ver
   `docs/decisions.md`).
