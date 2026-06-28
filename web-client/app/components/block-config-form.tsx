import { useState } from "react";

import { Field, FieldLabel } from "~/components/ui/field";
import { Input } from "~/components/ui/input";

type SchemaProp = {
  type?: string;
  anyOf?: { type?: string }[];
  default?: unknown;
  title?: string;
};

type Schema = { properties?: Record<string, SchemaProp> };

function numericProps(schema: Schema): [string, SchemaProp][] {
  return Object.entries(schema.properties ?? {}).filter(([name, p]) => {
    if (name === "type") return false;
    const types = [p.type, ...(p.anyOf?.map((a) => a.type) ?? [])];
    return types.includes("number") || types.includes("integer");
  });
}

export function useBlockConfig(schema: Schema) {
  const [values, setValues] = useState<Record<string, number>>({});
  const fields = numericProps(schema);
  return {
    fields,
    values,
    set: (name: string, v: number | undefined) =>
      setValues((prev) => {
        const next = { ...prev };
        if (v === undefined || Number.isNaN(v)) delete next[name];
        else next[name] = v;
        return next;
      }),
  };
}

export function BlockConfigForm({
  config,
}: {
  config: ReturnType<typeof useBlockConfig>;
}) {
  if (!config.fields.length) return null;
  return (
    <div className="grid grid-cols-2 gap-2">
      {config.fields.map(([name, prop]) => (
        <Field key={name}>
          <FieldLabel className="text-xs">{prop.title ?? name}</FieldLabel>
          <Input
            type="number"
            className="h-8"
            placeholder={
              prop.default !== undefined && prop.default !== null
                ? String(prop.default)
                : undefined
            }
            value={config.values[name] ?? ""}
            onChange={(e) =>
              config.set(
                name,
                e.target.value === "" ? undefined : e.target.valueAsNumber,
              )
            }
          />
        </Field>
      ))}
    </div>
  );
}
