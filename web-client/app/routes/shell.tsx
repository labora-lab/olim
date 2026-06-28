import { useState } from "react";
import { NavLink, Outlet, useParams } from "react-router";

import { CreateDatasetDialog } from "~/components/create-dataset-dialog";
import { icons } from "~/components/icons";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarProvider,
  SidebarRail,
} from "~/components/ui/sidebar";
import { useDatasets } from "~/hooks/datasets";

export default function Shell() {
  const [creating, setCreating] = useState(false);
  const datasets = useDatasets();
  const { datasetId } = useParams();

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <NavLink to="/">
                  <div className="bg-primary text-primary-foreground flex aspect-square size-8 items-center justify-center rounded-md">
                    <icons.sparkles className="size-4" />
                  </div>
                  <div className="grid flex-1 text-left leading-tight">
                    <span className="truncate font-heading font-semibold">
                      OLIM
                    </span>
                    <span className="text-muted-foreground truncate text-xs">
                      label · train · repeat
                    </span>
                  </div>
                </NavLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Datasets</SidebarGroupLabel>
            <SidebarGroupAction
              title="New dataset"
              onClick={() => setCreating(true)}
            >
              <icons.add /> <span className="sr-only">New dataset</span>
            </SidebarGroupAction>
            <SidebarGroupContent>
              <SidebarMenu>
                {datasets.isPending ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <SidebarMenuItem key={i}>
                      <SidebarMenuSkeleton showIcon />
                    </SidebarMenuItem>
                  ))
                ) : datasets.data?.length ? (
                  datasets.data.map((ds) => (
                    <SidebarMenuItem key={ds.id}>
                      <SidebarMenuButton
                        asChild
                        isActive={String(ds.id) === datasetId}
                        tooltip={ds.name}
                      >
                        <NavLink to={`/datasets/${ds.id}`}>
                          <icons.dataset />
                          <span className="truncate">{ds.name}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))
                ) : (
                  <p className="text-muted-foreground px-2 py-1.5 text-xs group-data-[collapsible=icon]:hidden">
                    No datasets yet.
                  </p>
                )}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarRail />
      </Sidebar>

      <SidebarInset className="min-w-0">
        <Outlet />
      </SidebarInset>

      <CreateDatasetDialog open={creating} onOpenChange={setCreating} />
    </SidebarProvider>
  );
}
