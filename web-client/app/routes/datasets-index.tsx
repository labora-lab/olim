import { useState } from "react";
import { Link } from "react-router";

import { CreateDatasetDialog } from "~/components/create-dataset-dialog";
import { icons } from "~/components/icons";
import { PageHeader } from "~/components/page-header";
import { Button } from "~/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "~/components/ui/item";
import { Skeleton } from "~/components/ui/skeleton";
import { useDatasets } from "~/hooks/datasets";

export function meta() {
  return [{ title: "OLIM" }];
}

export default function DatasetsIndex() {
  const [creating, setCreating] = useState(false);
  const datasets = useDatasets();

  return (
    <>
      <PageHeader
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <icons.add /> New dataset
          </Button>
        }
      >
        <span className="font-heading text-sm font-semibold">Datasets</span>
      </PageHeader>

      <div className="p-4">
        {datasets.isPending ? (
          <ItemGroup className="gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-lg" />
            ))}
          </ItemGroup>
        ) : datasets.data?.length ? (
          <ItemGroup className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {datasets.data.map((ds) => (
              <Item key={ds.id} asChild variant="outline" size="sm">
                <Link to={`/datasets/${ds.id}`}>
                  <ItemMedia variant="icon">
                    <icons.dataset />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>{ds.name}</ItemTitle>
                    <ItemDescription>{ds.data_type}</ItemDescription>
                  </ItemContent>
                  <icons.next className="text-muted-foreground" />
                </Link>
              </Item>
            ))}
          </ItemGroup>
        ) : (
          <Empty className="mt-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <icons.dataset />
              </EmptyMedia>
              <EmptyTitle>No datasets</EmptyTitle>
              <EmptyDescription>
                Create one to start labelling and training.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button onClick={() => setCreating(true)}>
                <icons.add /> New dataset
              </Button>
            </EmptyContent>
          </Empty>
        )}
      </div>

      <CreateDatasetDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
