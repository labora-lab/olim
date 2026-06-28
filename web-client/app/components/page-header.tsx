import { SidebarTrigger } from "~/components/ui/sidebar";
import { Separator } from "~/components/ui/separator";

export function PageHeader({
  children,
  actions,
}: {
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="bg-background/80 sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b px-3 backdrop-blur">
      <SidebarTrigger />
      <Separator orientation="vertical" className="mr-1 h-5!" />
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      {actions ? (
        <div className="flex items-center gap-1">{actions}</div>
      ) : null}
    </header>
  );
}
