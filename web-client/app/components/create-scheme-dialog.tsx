import { useState } from "react";

import { icons } from "~/components/icons";
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
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "~/components/ui/input-group";
import { Item, ItemActions, ItemContent } from "~/components/ui/item";
import { ScrollArea } from "~/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { useCreateScheme } from "~/hooks/schemes";
import type { FieldType } from "~/types/common";
import type { FieldIn } from "~/types/scheme";

type Draft = {
  key: number;
  name: string;
  type: FieldType;
  multi: boolean;
  options: string[];
};

let nextKey = 1;
const newDraft = (): Draft => ({
  key: nextKey++,
  name: "",
  type: "select",
  multi: false,
  options: [],
});

const FIELD_TYPES: FieldType[] = ["select", "boolean", "numeric", "text"];

function toFieldIn(d: Draft): FieldIn {
  switch (d.type) {
    case "select":
      return {
        type: "select",
        name: d.name.trim(),
        multi: d.multi,
        options: d.options.map((name) => ({ name })),
      };
    case "boolean":
      return { type: "boolean", name: d.name.trim() };
    case "numeric":
      return { type: "numeric", name: d.name.trim() };
    case "text":
      return { type: "text", name: d.name.trim() };
  }
}

export function CreateSchemeDialog({
  datasetId,
  open,
  onOpenChange,
}: {
  datasetId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [fields, setFields] = useState<Draft[]>(() => [newDraft()]);
  const create = useCreateScheme(datasetId);

  function patch(key: number, p: Partial<Draft>) {
    setFields((fs) => fs.map((f) => (f.key === key ? { ...f, ...p } : f)));
  }

  function reset() {
    setName("");
    setFields([newDraft()]);
  }

  const valid =
    name.trim() &&
    fields.length > 0 &&
    fields.every(
      (f) => f.name.trim() && (f.type !== "select" || f.options.length > 0),
    );

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    create.mutate(
      { name: name.trim(), fields: fields.map(toFieldIn) },
      {
        onSuccess: () => {
          onOpenChange(false);
          reset();
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New scheme</DialogTitle>
            <DialogDescription>
              Define the questions to answer for each item.
            </DialogDescription>
          </DialogHeader>

          <div className="my-4 space-y-3">
            <Field>
              <FieldLabel htmlFor="scheme-name">Scheme name</FieldLabel>
              <Input
                id="scheme-name"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="sentiment"
              />
            </Field>

            <ScrollArea className="max-h-72 -mx-1 px-1">
              <div className="space-y-2">
                {fields.map((f) => (
                  <FieldRow
                    key={f.key}
                    draft={f}
                    onPatch={(p) => patch(f.key, p)}
                    onRemove={
                      fields.length > 1
                        ? () =>
                            setFields((fs) => fs.filter((x) => x.key !== f.key))
                        : undefined
                    }
                  />
                ))}
              </div>
            </ScrollArea>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => setFields((fs) => [...fs, newDraft()])}
            >
              <icons.add /> Add field
            </Button>
          </div>

          <DialogFooter>
            <Button type="submit" disabled={!valid || create.isPending}>
              Create scheme
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function FieldRow({
  draft,
  onPatch,
  onRemove,
}: {
  draft: Draft;
  onPatch: (p: Partial<Draft>) => void;
  onRemove?: () => void;
}) {
  const [optionText, setOptionText] = useState("");

  function addOption() {
    const v = optionText.trim();
    if (!v || draft.options.includes(v)) return;
    onPatch({ options: [...draft.options, v] });
    setOptionText("");
  }

  return (
    <Item variant="outline" size="sm" className="flex-col items-stretch gap-2">
      <div className="flex items-center gap-2">
        <Input
          value={draft.name}
          onChange={(e) => onPatch({ name: e.target.value })}
          placeholder="field name"
          className="h-8"
        />
        <Select
          value={draft.type}
          onValueChange={(v) => onPatch({ type: v as FieldType })}
        >
          <SelectTrigger size="sm" className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FIELD_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {onRemove ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onRemove}
            aria-label="Remove field"
          >
            <icons.remove />
          </Button>
        ) : null}
      </div>

      {draft.type === "select" ? (
        <ItemContent className="gap-2">
          <InputGroup>
            <InputGroupInput
              value={optionText}
              onChange={(e) => setOptionText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addOption();
                }
              }}
              placeholder="add option, Enter"
            />
            <InputGroupAddon align="inline-end">
              <InputGroupButton onClick={addOption}>Add</InputGroupButton>
            </InputGroupAddon>
          </InputGroup>
          {draft.options.length ? (
            <ItemActions className="flex-wrap justify-start gap-1">
              {draft.options.map((o) => (
                <Button
                  key={o}
                  type="button"
                  variant="secondary"
                  size="xs"
                  onClick={() =>
                    onPatch({
                      options: draft.options.filter((x) => x !== o),
                    })
                  }
                >
                  {o} <icons.close className="size-3" />
                </Button>
              ))}
            </ItemActions>
          ) : null}
          <label className="text-muted-foreground flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={draft.multi}
              onChange={(e) => onPatch({ multi: e.target.checked })}
            />
            allow multiple
          </label>
        </ItemContent>
      ) : null}
    </Item>
  );
}
