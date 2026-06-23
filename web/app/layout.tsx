import type { Metadata } from "next";
import { DashboardShell } from "@/components/dashboard-shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "ArmorIQ Guarded Agent",
  description: "Guarded AI agent with MCP support, policy controls, and live approvals."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <DashboardShell>{children}</DashboardShell>
      </body>
    </html>
  );
}
