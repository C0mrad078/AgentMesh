import { useEffect, useState, type FormEvent } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { VISUAL_PRESETS } from "@/game/office-domain/visualProfile";
import { useAgentsStore } from "@/stores/agentsStore";
import type { Agent, ExecutionBackendType, Project } from "@/types";
import type { RuntimeBinding } from "@/services/api";

const BACKEND_OPTIONS: { value: ExecutionBackendType | ""; label: string }[] = [
  { value: "", label: "Sem preferência" },
  { value: "subscription", label: "Subscription" },
  { value: "session", label: "Session" },
  { value: "api", label: "API" },
];

interface AgentFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `null`/undefined = create mode; a real `Agent` = edit mode. */
  agent?: Agent | null;
  projects: Project[];
  runtimeBindings?: RuntimeBinding[];
}

/**
 * AgentMash V2, Phase 4 ("AGENT CREATION FLOW" / "TEAM PAGE"): the one
 * real form for creating or editing a persistent agent -- name, role,
 * description, provider preference, runtime preference, project
 * assignment, and visual preset. Team assignment itself is a separate
 * action (`TeamPage`'s own team-membership controls), matching the
 * brief's own "Assign Project" / "Assign Team" as two distinct actions.
 */
export function AgentFormDialog({ open, onOpenChange, agent, projects, runtimeBindings = [] }: AgentFormDialogProps) {
  const createAgent = useAgentsStore((s) => s.createAgent);
  const updateAgent = useAgentsStore((s) => s.updateAgent);
  const isEditing = !!agent;

  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState("mock");
  const [runtimeBindingId, setRuntimeBindingId] = useState("");
  const [maxSessions, setMaxSessions] = useState(1);
  const [projectId, setProjectId] = useState<string>("");
  const [preferredBackend, setPreferredBackend] = useState<ExecutionBackendType | "">("");
  const [visualPreset, setVisualPreset] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(agent?.name ?? "");
    setRole(agent?.role ?? "");
    setDescription(agent?.description ?? "");
    setProvider(agent?.provider ?? "mock");
    setRuntimeBindingId(agent?.runtime_binding_id ?? "");
    setMaxSessions(agent?.max_sessions ?? 1);
    setProjectId(agent?.project_id ?? "");
    setPreferredBackend(agent?.preferred_backend ?? "");
    setVisualPreset(agent?.visual_profile.preset ?? "");
    setError(null);
  }, [open, agent]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Informe um nome para o agente.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const shared = {
        name: name.trim(),
        role: role.trim(),
        description: description.trim(),
        provider: provider.trim() || "mock",
        runtime_binding_id: runtimeBindingId || null,
        max_sessions: maxSessions,
        preferred_backend: preferredBackend || null,
        project_id: projectId || null,
        visual_profile: (visualPreset ? { preset: visualPreset } : {}) as Record<string, string>,
      };
      if (isEditing && agent) {
        await updateAgent(agent.id, shared);
      } else {
        await createAgent(shared);
      }
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={(e) => void handleSubmit(e)}>
          <DialogHeader>
            <DialogTitle>{isEditing ? "Editar agente" : "Novo agente"}</DialogTitle>
            <DialogDescription>
              Um agente é persistente -- pode ser associado a um projeto e a equipes, e mantém sua
              identidade entre sessões.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="agent-name">Nome</Label>
              <Input id="agent-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Atlas" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="agent-role">Função</Label>
              <Input id="agent-role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Ex: Software Architect" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="agent-description">Descrição (opcional)</Label>
              <Textarea id="agent-description" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-project">Projeto</Label>
                <select
                  id="agent-project"
                  className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">Nenhum</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-backend">Runtime preferido</Label>
                <select
                  id="agent-backend"
                  className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                  value={preferredBackend}
                  onChange={(e) => setPreferredBackend(e.target.value as ExecutionBackendType | "")}
                >
                  {BACKEND_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-provider">Provider</Label>
                <Input id="agent-provider" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="mock" />
              </div>
              <div className="flex flex-col gap-1.5">
                  <Label htmlFor="agent-binding">RuntimeBinding</Label>
                <select id="agent-binding" className="h-9 rounded-md border border-input bg-transparent px-2 text-sm" value={runtimeBindingId} onChange={(e) => setRuntimeBindingId(e.target.value)}>
                  <option value="">Automático</option>
                  {runtimeBindings.map((binding) => <option key={binding.id} value={binding.id} disabled={!binding.enabled}>{binding.label} · {binding.provider_id} · {binding.reserved_slots}/{binding.configured_capacity}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-max-sessions">Sessões simultâneas</Label>
                <Input id="agent-max-sessions" type="number" min={1} max={8} value={maxSessions} onChange={(e) => setMaxSessions(Math.max(1, Math.min(8, Number(e.target.value) || 1)))} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-visual">Visual no Office</Label>
                <select
                  id="agent-visual"
                  className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                  value={visualPreset}
                  onChange={(e) => setVisualPreset(e.target.value)}
                >
                  <option value="">Automático (por id)</option>
                  {VISUAL_PRESETS.map((preset) => (
                    <option key={preset.preset} value={preset.preset}>{preset.preset}</option>
                  ))}
                </select>
              </div>
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Salvando..." : isEditing ? "Salvar" : "Criar agente"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
