"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  accent?: boolean;
  external?: boolean;
}

interface NavSection {
  label?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { href: "/", label: "Dashboard", icon: "H" },
    ],
  },
  {
    label: "Forge",
    items: [
      { href: "/forge", label: "Brain Graph", icon: "B", accent: true },
      { href: "/forge/build", label: "Build Brain", icon: "+" },
      { href: "/forge/script", label: "Script Gen", icon: "S" },
    ],
  },
  {
    label: "Explore",
    items: [
      { href: "/knowledge", label: "Knowledge", icon: "K" },
      { href: "/knowledge/components", label: "Components", icon: "C" },
      { href: "/knowledge/failure", label: "Failure KB", icon: "!" },
      { href: "/knowledge/gaps", label: "Gap Heatmap", icon: "G" },
      { href: "/knowledge/attribution", label: "Attribution", icon: "A" },
      { href: "/federation", label: "Federation", icon: "F" },
    ],
  },
  {
    label: "Operate",
    items: [
      { href: "/mining", label: "Mining", icon: "M" },
      { href: "/playground", label: "Playground", icon: "P" },
    ],
  },
  {
    label: "Analyze",
    items: [
      { href: "/evolution", label: "Evolution", icon: "E" },
      { href: "/costs", label: "Costs", icon: "C" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-card-border bg-card min-h-screen p-4 flex flex-col gap-1">
      <Link href="/" className="text-lg font-bold text-accent mb-4 block px-2">
        CAM-PULSE
      </Link>

      {NAV_SECTIONS.map((section, si) => (
        <div key={si}>
          {si > 0 && <div className="border-t border-card-border mt-2 pt-2" />}
          {section.label && (
            <div className="text-[10px] text-muted-dark uppercase tracking-wider px-3 mt-4 mb-1">
              {section.label}
            </div>
          )}
          {section.items.map((item) => {
            const active =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  active
                    ? "bg-accent/10 text-accent font-medium"
                    : "text-muted hover:text-foreground hover:bg-card-border/50"
                }`}
              >
                <span
                  className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold ${
                    active || item.accent
                      ? "bg-accent text-white"
                      : "bg-card-border text-muted"
                  }`}
                >
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}

      <div className="mt-auto pt-4 border-t border-card-border">
        <a
          href="http://localhost:8420/api/docs"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-muted-dark hover:text-muted px-3"
        >
          API Docs
        </a>
      </div>
    </aside>
  );
}
