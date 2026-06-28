import { useState } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Textarea } from "~/components/ui/textarea";
import { useUploadItems } from "~/hooks/items";

export function UploadItemsDialog({
  datasetId,
  open,
  onOpenChange,
}: {
  datasetId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [text, setText] = useState("");
  const upload = useUploadItems(datasetId);

  // ponytail: one item per non-empty line — covers paste-from-spreadsheet.
  const contents = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!contents.length) return;
    upload.mutate(
      { contents },
      {
        onSuccess: (items) => {
          onOpenChange(false);
          setText("");
          toast.success(`Uploaded ${items.length} items`);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Upload items</DialogTitle>
            <DialogDescription>
              One text item per line. Empty lines are ignored.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"great movie, loved it\nterrible, fell asleep"}
            className="my-4 min-h-40 font-mono text-sm"
          />
          <DialogFooter className="items-center">
            <span className="text-muted-foreground mr-auto text-xs">
              {contents.length} item{contents.length === 1 ? "" : "s"}
            </span>
            <Button
              type="submit"
              disabled={!contents.length || upload.isPending}
            >
              Upload
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
