"use client";

import { AppHeader, Crumbs, PageHeader } from "@claimpilot/ui";

/**
 * Data page: 47 px header with the breadcrumb, then the page title block
 * at 42 / 60 px and the content 40 px below it.
 */
export function DataPage({
  crumbs,
  meta,
  actions,
  title,
  subtitle,
  children,
}: {
  crumbs: { label: string; href?: string }[];
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-col">
      <AppHeader crumbs={<Crumbs items={crumbs} />} meta={meta} actions={actions} className="sticky top-0 z-10" />
      <div className="flex animate-rise flex-col px-60 pb-40 pt-42">
        <PageHeader variant="data" title={title} subtitle={subtitle} />
        <div className="mt-40 flex flex-col gap-12">{children}</div>
      </div>
    </div>
  );
}
