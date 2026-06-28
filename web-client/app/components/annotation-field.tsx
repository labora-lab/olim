import { Button } from "~/components/ui/button";
import { Field, FieldLabel } from "~/components/ui/field";
import { Input } from "~/components/ui/input";
import { Textarea } from "~/components/ui/textarea";
import { cn } from "~/lib/utils";
import type { AnnotationValue } from "~/types/annotation";
import type { FieldDTO } from "~/types/scheme";

// What a control reports for one field. Mirrors the API's AnswerIn.value:
// select -> an option id (number) or list of ids (multi), or text (allow_other).
export type FieldValue = AnnotationValue | number[];

export function AnnotationField({
  field,
  value,
  onChange,
}: {
  field: FieldDTO;
  value: FieldValue;
  onChange: (value: FieldValue) => void;
}) {
  return (
    <Field>
      <FieldLabel>{field.name}</FieldLabel>
      {field.type === "select" ? (
        <SelectControl field={field} value={value} onChange={onChange} />
      ) : field.type === "boolean" ? (
        <BooleanControl field={field} value={value} onChange={onChange} />
      ) : field.type === "numeric" ? (
        <Input
          type="number"
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? undefined}
          value={typeof value === "number" ? value : ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : e.target.valueAsNumber)
          }
        />
      ) : (
        <Textarea
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-20"
        />
      )}
    </Field>
  );
}

// The API stores option ids: multi -> number[], single -> a single number id.
function SelectControl({
  field,
  value,
  onChange,
}: {
  field: FieldDTO;
  value: FieldValue;
  onChange: (value: FieldValue) => void;
}) {
  const selected = new Set(
    Array.isArray(value) ? value : typeof value === "number" ? [value] : [],
  );

  function toggle(id: number) {
    if (field.multi) {
      const next = new Set(selected);
      next.has(id) ? next.delete(id) : next.add(id);
      onChange([...next]);
    } else {
      onChange(selected.has(id) ? null : id);
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {field.options.map((o) => {
        const active = selected.has(o.id);
        return (
          <Button
            key={o.id}
            type="button"
            size="sm"
            variant={active ? "default" : "outline"}
            onClick={() => toggle(o.id)}
            className={cn(!active && "text-muted-foreground")}
          >
            {o.name}
          </Button>
        );
      })}
    </div>
  );
}

function BooleanControl({
  field,
  value,
  onChange,
}: {
  field: FieldDTO;
  value: FieldValue;
  onChange: (value: FieldValue) => void;
}) {
  const choices: { label: string; v: AnnotationValue }[] = [
    { label: "Yes", v: true },
    { label: "No", v: false },
  ];
  if (field.nullable) choices.push({ label: "Unknown", v: null });

  return (
    <div className="flex gap-1.5">
      {choices.map((c) => (
        <Button
          key={c.label}
          type="button"
          size="sm"
          variant={value === c.v ? "default" : "outline"}
          onClick={() => onChange(c.v)}
        >
          {c.label}
        </Button>
      ))}
    </div>
  );
}
