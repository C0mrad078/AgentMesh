import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { databaseApi, learningApi, type DatabaseBackupInfo } from "@/services/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DataManagementSettings() {
  const [backups, setBackups] = useState<DatabaseBackupInfo[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmingRestore, setConfirmingRestore] = useState<string | null>(null);

  async function reload() {
    setBackups(await databaseApi.listBackups());
  }

  useEffect(() => {
    void reload();
  }, []);

  async function handleCreateBackup() {
    setBusy("backup");
    setMessage(null);
    try {
      const info = await databaseApi.createBackup();
      setMessage(`Backup criado: ${info.path}`);
      await reload();
    } finally {
      setBusy(null);
    }
  }

  async function handleRestore(path: string) {
    setBusy("restore");
    setMessage(null);
    try {
      await databaseApi.restoreBackup(path);
      setMessage(
        "Dados restaurados. Reinicie o Orquestrador para garantir que todo o estado em memória reflita o backup.",
      );
      setConfirmingRestore(null);
    } finally {
      setBusy(null);
    }
  }

  async function handleIntegrityCheck() {
    setBusy("integrity");
    setMessage(null);
    try {
      const result = await databaseApi.integrityCheck();
      setMessage(result.ok ? "Banco de dados íntegro." : `Problemas encontrados: ${result.issues.join(", ")}`);
    } finally {
      setBusy(null);
    }
  }

  async function handleExportLearning() {
    setBusy("export");
    setMessage(null);
    try {
      const data = await learningApi.export();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "orquestrador-learning-export.json";
      link.click();
      URL.revokeObjectURL(url);
      setMessage("Dados de aprendizado exportados.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy !== null} onClick={() => void handleCreateBackup()}>
          {busy === "backup" ? <Loader2 className="size-4 animate-spin" /> : "Fazer backup agora"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void handleIntegrityCheck()}>
          {busy === "integrity" ? <Loader2 className="size-4 animate-spin" /> : "Verificar integridade"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void handleExportLearning()}>
          {busy === "export" ? <Loader2 className="size-4 animate-spin" /> : "Exportar dados de aprendizado"}
        </Button>
      </div>
      {message && <p className="text-xs text-muted-foreground">{message}</p>}

      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-muted-foreground">Backups disponíveis</p>
        {backups === null ? (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        ) : backups.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nenhum backup ainda.</p>
        ) : (
          backups.map((backup) => (
            <div key={backup.path} className="flex items-center justify-between rounded-md border border-border p-2 text-xs">
              <div>
                <p>{backup.created_at}</p>
                <Badge variant="outline">{formatBytes(backup.size_bytes)}</Badge>
              </div>
              {confirmingRestore === backup.path ? (
                <div className="flex gap-2">
                  <Button size="sm" variant="destructive" disabled={busy !== null} onClick={() => void handleRestore(backup.path)}>
                    Confirmar restauração
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmingRestore(null)}>
                    Cancelar
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setConfirmingRestore(backup.path)}>
                  Restaurar
                </Button>
              )}
            </div>
          ))
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Restaurar substitui os dados atuais pelos do backup selecionado (o estado atual é
        automaticamente salvo antes, como uma rede de segurança). Segredos (chaves de API) não
        fazem parte do backup/exportação -- eles ficam apenas no Keychain/Credential Manager do
        sistema operacional.
      </p>
    </div>
  );
}
