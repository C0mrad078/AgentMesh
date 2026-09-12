# Empacotamento (build de distribuição)

Este documento descreve como o Orquestrador é (e será) empacotado como
aplicativo desktop instalável em macOS e Windows. **Nada neste documento foi
executado neste ambiente de desenvolvimento** — não há aqui um toolchain de
build completo (Xcode/`codesign`/`notarytool`, WiX/Authenticode, nem mesmo
`cargo`/Rust). Cada etapa que depende de uma ferramenta ou credencial
externa está marcada explicitamente como `UNVERIFIED EXTERNAL DEPENDENCY` —
o processo está documentado com precisão suficiente para ser executado e
verificado em uma máquina com o toolchain real, mas não foi verificado
aqui.

## Visão geral do pipeline de empacotamento

```
core/ (Python)  ──PyInstaller/Nuitka──▶  binário sidecar único
                                              │
desktop/ (React) ──vite build──▶ dist/        │
                                              ▼
                              Tauri bundle (src-tauri/tauri.conf.json)
                                              │
                        ┌─────────────────────┼─────────────────────┐
                        ▼                                           ▼
                 macOS: .app → .dmg                       Windows: .msi / .exe (NSIS)
                 (codesign + notarytool)                  (Authenticode signtool)
```

O sidecar Python é compilado para um binário standalone (sem exigir Python
instalado na máquina do usuário) e embutido como
[`externalBin`](https://tauri.app/v1/api/config/#bundleconfig.externalbin)
no bundle Tauri, que é quem produz o instalador final por plataforma.

## 1. Empacotar o core Python como sidecar

Escolha registrada em `docs/decisions.md`: **PyInstaller** (`--onefile`) é a
opção padrão por maturidade e suporte multiplataforma; Nuitka é uma
alternativa aceitável (compila para C, binário menor e mais rápido de
iniciar) se o tempo de build do PyInstaller se tornar um problema.

```bash
pip install pyinstaller
pyinstaller \
  --onefile \
  --name orchestrator-core-x86_64-apple-darwin \
  --paths . \
  core/bridge/__main__.py
```

O nome do binário **precisa** seguir a convenção de target-triple exigida
pelo Tauri para sidecars (`<nome>-<target-triple>`, ex.:
`orchestrator-core-x86_64-apple-darwin`, `orchestrator-core-x86_64-pc-windows-msvc.exe`,
`orchestrator-core-aarch64-apple-darwin`) — sem isso o Tauri não localiza o
binário certo por plataforma/arquitetura no momento do bundle.

Repita para cada combinação de SO/arquitetura alvo (macOS Intel, macOS
Apple Silicon, Windows x86_64). **`UNVERIFIED EXTERNAL DEPENDENCY`** — não
há PyInstaller nem os toolchains de compilação nativa (necessários para
extensões C de algumas dependências) disponíveis neste ambiente.

## 2. Configurar o sidecar no Tauri

Em `desktop/src-tauri/tauri.conf.json`, `bundle.externalBin` deve apontar
para o binário gerado no passo 1 (caminho relativo, sem o sufixo de
target-triple — o Tauri o adiciona automaticamente na hora de resolver por
plataforma):

```json
{
  "bundle": {
    "externalBin": ["binaries/orchestrator-core"]
  }
}
```

`desktop/src-tauri/src/bridge/manager.rs` já usa
`tauri_plugin_shell::process::Command::sidecar("orchestrator-core")` (não um
caminho de Python + script) — isso já está implementado desde os estágios
anteriores; este passo é só sobre colocar o binário certo no lugar certo
antes de rodar `tauri build`.

## 3. macOS: `.app` e `.dmg`

```bash
cd desktop
npm run tauri build -- --target universal-apple-darwin
```

Isso produz `src-tauri/target/.../bundle/macos/Orquestrador.app` e
`.../dmg/Orquestrador_<versão>_universal.dmg`.

### Assinatura de código (`codesign`)

Requer um **Developer ID Application** certificate válido (Apple Developer
Program). Configurado via variáveis de ambiente lidas pelo Tauri:

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: <Nome> (<TEAM_ID>)"
export APPLE_CERTIFICATE="<base64 do .p12>"
export APPLE_CERTIFICATE_PASSWORD="<senha do .p12>"
```

### Notarização (`notarytool`)

Requer uma **App Store Connect API key** (ou Apple ID + senha de app):

```bash
export APPLE_API_ISSUER="<issuer id>"
export APPLE_API_KEY="<key id>"
export APPLE_API_KEY_PATH="<caminho para a .p8>"
```

Com essas variáveis presentes, `tauri build` assina e notariza
automaticamente como parte do bundle; sem elas, produz um `.app`/`.dmg` não
assinado (utilizável apenas para teste local, o Gatekeeper bloqueia a
execução em outra máquina).

**`UNVERIFIED EXTERNAL DEPENDENCY`** — este projeto não possui um Apple
Developer Program certificate nem uma API key de App Store Connect
configurados neste ambiente. Nenhum `.app`/`.dmg` foi gerado, assinado ou
notarizado neste trabalho. Qualquer relatório que afirme "build de macOS
assinado e notarizado com sucesso" sem essas credenciais reais estaria
falso — este documento evita essa afirmação deliberadamente.

## 4. Windows: `.msi` / `.exe` (NSIS)

```powershell
cd desktop
npm run tauri build
```

Produz, por padrão, ambos `bundle/msi/Orquestrador_<versão>_x64_en-US.msi`
e `bundle/nsis/Orquestrador_<versão>_x64-setup.exe` (configurável em
`tauri.conf.json::bundle.windows`).

### Assinatura Authenticode

Requer um code-signing certificate (`.pfx`) de uma CA reconhecida (ou EV
certificate para evitar o aviso do SmartScreen):

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = "<caminho ou conteúdo do .pfx>"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "<senha>"
```

**`UNVERIFIED EXTERNAL DEPENDENCY`** — nenhum certificate de assinatura de
código Windows está disponível neste ambiente (que, além disso, é macOS —
o build nativo do instalador Windows normalmente roda em um runner Windows
do CI, ver `.github/workflows/ci.yml`). Nenhum `.msi`/`.exe` foi gerado ou
assinado neste trabalho.

## 5. Auto-update

O Tauri Updater plugin (`tauri-plugin-updater`) verifica assinatura
Ed25519 do artefato de atualização contra uma chave pública embutida no
binário antes de aplicar qualquer atualização — isso é uma verificação
*além* da assinatura de código do SO, específica do Tauri, e é o mecanismo
que impede uma atualização adulterada de ser instalada mesmo que o canal de
distribuição (ex.: um mirror de download) seja comprometido.

Fluxo pretendido (não implementado neste estágio além da configuração):

1. Release assinada publicada com um `latest.json` (formato do Tauri
   Updater) contendo versão, notas e URL/assinatura por plataforma.
2. O app verifica esse endpoint periodicamente (ou sob demanda, via um
   botão em "Sobre") e, se uma versão mais nova existir e a assinatura
   verificar, baixa e aplica no próximo reinício.
3. Nenhuma atualização é aplicada silenciosamente sem a verificação de
   assinatura passar — uma falha de verificação descarta o artefato e não
   afeta a instalação atual.

**`UNVERIFIED EXTERNAL DEPENDENCY`** — o par de chaves Ed25519 de
atualização não foi gerado, e nenhum servidor de atualização/`latest.json`
real existe ainda. O plugin está listado como dependência pretendida, mas
habilitá-lo de fato (gerar chaves, publicar o endpoint) fica fora do escopo
executável deste ambiente.

## Checklist de verificação real (para quem tiver o toolchain)

- [ ] `pyinstaller` gera um binário que roda sozinho (`./orchestrator-core-<triple> --selftest` ou equivalente) sem Python instalado na máquina de teste.
- [ ] `tauri build` produz `.app`/`.dmg` no macOS e abre sem erro do Gatekeeper após assinatura + notarização.
- [ ] `spctl -a -vv Orquestrador.app` reporta `accepted` e `source=Notarized Developer ID`.
- [ ] `tauri build` produz `.msi`/`.exe` no Windows e o SmartScreen não bloqueia após assinatura.
- [ ] Um artefato de atualização de teste, assinado, é aceito pelo Updater; um artefato com assinatura adulterada é rejeitado.
