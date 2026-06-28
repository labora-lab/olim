import { useEffect, useState } from "react";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Field, FieldLabel } from "~/components/ui/field";
import { Input } from "~/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { useCreatePipeline } from "~/hooks/pipelines";
import { useSchemes } from "~/hooks/schemes";

export function CreatePipelineDialog({
  datasetId,
  open,
  onOpenChange,
  onCreated,
}: {
  datasetId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (pipelineId: number) => void;
}) {
  const [name, setName] = useState("");
  const [schemeId, setSchemeId] = useState<number | null>(null);
  const schemes = useSchemes(datasetId);

  useEffect(() => {
    if (schemeId === null && schemes.data?.length) {
      setSchemeId(schemes.data[0].id);
    }
  }, [schemeId, schemes.data]);

  const create = useCreatePipeline(datasetId, schemeId ?? 0);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !schemeId) return;
    create.mutate(
      { name: name.trim() },
      {
        onSuccess: (p) => {
          onOpenChange(false);
          setName("");
          onCreated(p.id);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New pipeline</DialogTitle>
            <DialogDescription>
              Trains on the labels of one scheme.
            </DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-3">
            <Field>
              <FieldLabel htmlFor="pipeline-name">Name</FieldLabel>
              <Input
                id="pipeline-name"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="baseline"
              />
            </Field>
            <Field>
              <FieldLabel>Scheme</FieldLabel>
              <Select
                value={schemeId ? String(schemeId) : undefined}
                onValueChange={(v) => setSchemeId(Number(v))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Pick a scheme" />
                </SelectTrigger>
                <SelectContent>
                  {schemes.data?.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={!name.trim() || !schemeId || create.isPending}
            >
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
