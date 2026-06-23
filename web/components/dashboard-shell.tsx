"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

const NAV = [
  { href: "/chat", label: "Agent Chat" },
  { href: "/policies", label: "Policies" },
  { href: "/approvals", label: "Approvals" },
  { href: "/logs", label: "Audit Logs" },
  { href: "/mcp-servers", label: "MCP Servers" }
];

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>ArmorIQ Guarded Agent</h1>
          <p>
            Live MCP discovery, policy enforcement, approvals, and audit trails from one
            control plane.
          </p>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-link${pathname === item.href ? " active" : ""}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>

      <main className="content">{children}</main>
    </div>
  );
}
