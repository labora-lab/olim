import { NavLink, Outlet } from "react-router";

import { icons } from "~/components/icons";
import { PageHeader } from "~/components/page-header";
import { cn } from "~/lib/utils";
import { useDataset } from "~/hooks/datasets";
import type { Route } from "./+types/dataset";

const tabs = [
  { to: ".", label: "Overview", end: true, icon: icons.dataset },
  { to: "annotate", label: "Annotate", end: false, icon: icons.annotate },
  { to: "pipelines", label: "Pipelines", end: false, icon: icons.pipeline },
] as const;

export default function Dataset({ params }: Route.ComponentProps) {
  const id = Number(params.datasetId);
  const dataset = useDataset(id);

  return (
    <>
      <PageHeader>
        <icons.dataset className="text-muted-foreground shrink-0" />
        <span className="truncate font-heading text-sm font-semibold">
          {dataset.data?.name ?? "…"}
        </span>
        <nav className="ml-2 flex items-center gap-1">
          {tabs.map((t) => (
            <NavLink
              key={t.label}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                )
              }
            >
              <t.icon className="size-3.5" />
              <span className="hidden sm:inline">{t.label}</span>
            </NavLink>
          ))}
        </nav>
      </PageHeader>
      <div className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </div>
    </>
  );
}
