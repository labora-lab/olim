import { useState } from "react";
import { useNavigate } from "react-router";

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
import { useCreateDataset } from "~/hooks/datasets";

export function CreateDatasetDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = useState("");
  const navigate = useNavigate();
  const create = useCreateDataset();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate(
      { name: trimmed },
      {
        onSuccess: (ds) => {
          onOpenChange(false);
          setName("");
          navigate(`/datasets/${ds.id}`);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New dataset</DialogTitle>
            <DialogDescription>
              A container for items, schemes, and pipelines.
            </DialogDescription>
          </DialogHeader>
          <Field className="py-4">
            <FieldLabel htmlFor="dataset-name">Name</FieldLabel>
            <Input
              id="dataset-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="movie-reviews"
            />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
