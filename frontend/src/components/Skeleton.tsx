import React from "react";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`animate-pulse rounded-md bg-border/50 ${className || ""}`}
      {...props}
    />
  );
}

export function PanelSkeleton() {
  return (
    <div className="flex flex-col h-full bg-background p-4 animate-pulse">
      <div className="h-6 w-48 bg-surface rounded mb-6" />
      <div className="flex-1 rounded-lg border border-border bg-surface overflow-hidden">
        <div className="h-10 border-b border-border bg-surface-hover/50" />
        <div className="p-4 space-y-4">
          <div className="h-4 w-3/4 bg-border/50 rounded" />
          <div className="h-4 w-1/2 bg-border/50 rounded" />
          <div className="h-32 bg-border/30 rounded mt-8" />
        </div>
      </div>
    </div>
  );
}
