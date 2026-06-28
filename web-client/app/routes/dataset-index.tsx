import { useState } from "react";
import { Link } from "react-router";

import { CreateSchemeDialog } from "~/components/create-scheme-dialog";
import { icons } from "~/components/icons";
import { UploadItemsDialog } from "~/components/upload-items-dialog";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "~/components/ui/item";
import { Skeleton } from "~/components/ui/skeleton";
import { useItems } from "~/hooks/items";
import { useSchemes } from "~/hooks/schemes";
import type { Route } from "./+types/dataset-index";

export default function DatasetIndex({ params }: Route.ComponentProps) {
  const id = Number(params.datasetId);
  const items = useItems(id);
  const schemes = useSchemes(id);
  const [uploading, setUploading] = useState(false);
  const [creatingScheme, setCreatingScheme] = useState(false);

  return (
    <div className="grid gap-4 p-4 lg:grid-cols-2">
      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <icons.item className="size-4" /> Items
          </CardTitle>
          <CardDescription>
            {items.isPending ? "…" : `${items.data?.length ?? 0} items`}
          </CardDescription>
          <Button
            size="sm"
            variant="outline"
            className="col-start-2 row-span-2 row-start-1 self-center"
            onClick={() => setUploading(true)}
          >
            <icons.upload /> Upload
          </Button>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          {items.isPending ? (
            <Skeleton className="h-4 w-32" />
          ) : items.data?.length ? (
            <Link
              to="annotate"
              className="text-foreground inline-flex items-center gap-1 hover:underline"
            >
              Go annotate <icons.next className="size-3.5" />
            </Link>
          ) : (
            "Upload text items to begin."
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <icons.scheme className="size-4" /> Schemes
          </CardTitle>
          <CardDescription>The labelling questions.</CardDescription>
          <Button
            size="sm"
            variant="outline"
            className="col-start-2 row-span-2 row-start-1 self-center"
            onClick={() => setCreatingScheme(true)}
          >
            <icons.add /> New
          </Button>
        </CardHeader>
        <CardContent>
          {schemes.isPending ? (
            <Skeleton className="h-12 w-full" />
          ) : schemes.data?.length ? (
            <ItemGroup className="gap-1">
              {schemes.data.map((s) => (
                <Item key={s.id} variant="muted" size="xs">
                  <ItemMedia variant="icon">
                    <icons.scheme />
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle>{s.name}</ItemTitle>
                    <ItemDescription>
                      {s.fields.length} field
                      {s.fields.length === 1 ? "" : "s"}
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions>
                    {s.fields.slice(0, 4).map((f) => (
                      <Badge key={f.id} variant="secondary">
                        {f.type}
                      </Badge>
                    ))}
                  </ItemActions>
                </Item>
              ))}
            </ItemGroup>
          ) : (
            <p className="text-muted-foreground text-sm">
              No schemes yet. Add one to define what to label.
            </p>
          )}
        </CardContent>
      </Card>

      <UploadItemsDialog
        datasetId={id}
        open={uploading}
        onOpenChange={setUploading}
      />
      <CreateSchemeDialog
        datasetId={id}
        open={creatingScheme}
        onOpenChange={setCreatingScheme}
      />
    </div>
  );
}
