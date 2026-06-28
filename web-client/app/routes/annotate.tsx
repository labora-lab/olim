import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  AnnotationField,
  type FieldValue,
} from "~/components/annotation-field";
import { icons } from "~/components/icons";
import { Button } from "~/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { ScrollArea } from "~/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Skeleton } from "~/components/ui/skeleton";
import { cn } from "~/lib/utils";
import { useAnnotate, useAnnotations } from "~/hooks/annotations";
import { useItems } from "~/hooks/items";
import { useSchemes } from "~/hooks/schemes";
import type { Route } from "./+types/annotate";

export default function Annotate({ params }: Route.ComponentProps) {
  const datasetId = Number(params.datasetId);
  const items = useItems(datasetId);
  const schemes = useSchemes(datasetId);

  const [schemeId, setSchemeId] = useState<number | null>(null);
  const [activeItemId, setActiveItemId] = useState<number | null>(null);

  // Default to the first scheme / item once data lands.
  useEffect(() => {
    if (schemeId === null && schemes.data?.length) {
      setSchemeId(schemes.data[0].id);
    }
  }, [schemeId, schemes.data]);
  useEffect(() => {
    if (activeItemId === null && items.data?.length) {
      setActiveItemId(items.data[0].id);
    }
  }, [activeItemId, items.data]);

  const scheme = schemes.data?.find((s) => s.id === schemeId);
  const activeItem = items.data?.find((i) => i.id === activeItemId);

  function nextItem() {
    if (!items.data || activeItemId === null) return;
    const idx = items.data.findIndex((i) => i.id === activeItemId);
    const next = items.data[idx + 1];
    if (next) setActiveItemId(next.id);
  }

  if (items.isPending || schemes.isPending) {
    return <Skeleton className="m-4 h-96" />;
  }

  if (!items.data?.length || !schemes.data?.length) {
    return (
      <Empty className="mt-16">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <icons.annotate />
          </EmptyMedia>
          <EmptyTitle>Nothing to annotate yet</EmptyTitle>
          <EmptyDescription>
            {!items.data?.length
              ? "Upload some items first."
              : "Create a scheme to define the labels."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[16rem_1fr] divide-x">
      {/* Item list */}
      <ScrollArea className="h-[calc(100svh-3rem)]">
        <div className="p-2">
          {items.data.map((item, i) => (
            <button
              key={item.id}
              onClick={() => setActiveItemId(item.id)}
              className={cn(
                "flex w-full gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                item.id === activeItemId
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-accent/50",
              )}
            >
              <span className="text-muted-foreground tabular-nums">
                {i + 1}
              </span>
              <span className="truncate">{item.content}</span>
            </button>
          ))}
        </div>
      </ScrollArea>

      {/* Annotation panel */}
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2 border-b px-4 py-2">
          <span className="text-muted-foreground text-xs">Scheme</span>
          <Select
            value={schemeId ? String(schemeId) : undefined}
            onValueChange={(v) => setSchemeId(Number(v))}
          >
            <SelectTrigger size="sm" className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {schemes.data.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {activeItem && scheme ? (
          <AnnotationPanel
            key={`${activeItem.id}-${scheme.id}`}
            itemId={activeItem.id}
            content={activeItem.content}
            scheme={scheme}
            onSaved={nextItem}
          />
        ) : null}
      </div>
    </div>
  );
}

function AnnotationPanel({
  itemId,
  content,
  scheme,
  onSaved,
}: {
  itemId: number;
  content: string;
  scheme: NonNullable<ReturnType<typeof useSchemes>["data"]>[number];
  onSaved: () => void;
}) {
  const existing = useAnnotations(itemId);
  const annotate = useAnnotate(itemId);
  const [values, setValues] = useState<Record<number, FieldValue>>({});

  // Prefill from saved annotations. Each select option id is its own row, so a
  // multi-select collects them into a number[]; everything else is the scalar.
  const prefilled = useMemo(() => {
    const map: Record<number, FieldValue> = {};
    for (const a of existing.data ?? []) {
      const field = scheme.fields.find((f) => f.id === a.field_id);
      if (field?.type === "select" && field.multi && typeof a.value === "number") {
        const prev = map[a.field_id];
        map[a.field_id] = [...(Array.isArray(prev) ? prev : []), a.value];
      } else {
        map[a.field_id] = a.value;
      }
    }
    return map;
  }, [existing.data, scheme.fields]);

  useEffect(() => setValues(prefilled), [prefilled]);

  function isEmpty(v: FieldValue) {
    return v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
  }

  function save() {
    const answers = scheme.fields
      .filter((f) => !isEmpty(values[f.id]))
      .map((f) => ({ field_id: f.id, value: values[f.id] }));
    if (!answers.length) return;
    annotate.mutate(
      { answers },
      {
        onSuccess: () => {
          toast.success("Saved", { icon: null });
          onSaved();
        },
      },
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ScrollArea className="flex-1">
        <div className="space-y-6 p-4">
          <p className="bg-muted/40 rounded-md border p-3 text-sm leading-relaxed">
            {content}
          </p>
          <div className="space-y-5">
            {scheme.fields.map((field) => (
              <AnnotationField
                key={field.id}
                field={field}
                value={values[field.id] ?? null}
                onChange={(v) =>
                  setValues((prev) => ({ ...prev, [field.id]: v }))
                }
              />
            ))}
          </div>
        </div>
      </ScrollArea>
      <div className="flex items-center justify-end gap-2 border-t px-4 py-2">
        <Button onClick={save} disabled={annotate.isPending}>
          <icons.done /> Save &amp; next
        </Button>
      </div>
    </div>
  );
}
