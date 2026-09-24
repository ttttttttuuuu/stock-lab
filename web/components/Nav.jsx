"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, ArrowLeftRight, Radio, ClipboardCheck,
  FlaskConical, Layers, Calculator, Sun, Moon, Cloud, HardDrive,
} from "lucide-react";
import { DATA_SOURCE } from "../lib/data";

const links = [
  { href: "/", label: "仪表盘", icon: LayoutDashboard },
  { href: "/lab", label: "实验室", icon: FlaskConical, match: "/lab" },
  { href: "/sim", label: "资金模拟", icon: Calculator },
  { href: "/options", label: "期权", icon: Layers },
  { href: "/trades", label: "交易明细", icon: ArrowLeftRight },
  { href: "/signals", label: "信号与持仓", icon: Radio },
  { href: "/review", label: "复盘", icon: ClipboardCheck },
];

export default function Nav() {
  const path = usePathname();
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme || "dark");
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("wot-theme", next); } catch {}
    setTheme(next);
  };

  const cloud = DATA_SOURCE === "supabase";

  return (
    <div className="nav">
      <div className="nav-inner">
        <div className="brand">
          SWING<span>·</span>DESK
        </div>
        <nav className="nav-links" aria-label="主导航">
          {links.map((l) => {
            const Icon = l.icon;
            const active = l.match ? path.startsWith(l.match) : path === l.href;
            return (
              <Link key={l.href} href={l.href} className={active ? "active" : ""}
                    aria-label={l.label}
                    aria-current={active ? "page" : undefined}>
                <Icon size={15} strokeWidth={2} aria-hidden="true" />
                <span>{l.label}</span>
              </Link>
            );
          })}
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
          <button onClick={toggleTheme} className="theme-toggle"
                  aria-label={theme === "dark" ? "切换为浅色主题" : "切换为深色主题"}
                  title={theme === "dark" ? "切换为浅色主题" : "切换为深色主题"}>
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <span className="source-badge" title={cloud ? "数据来自 Supabase 云端" : "数据来自本地导出"}>
            {cloud ? <Cloud size={13} aria-hidden="true" /> : <HardDrive size={13} aria-hidden="true" />}
            <span className={`source-dot ${cloud ? "on" : ""}`} aria-hidden="true" />
            {cloud ? "Supabase" : "Local"}
          </span>
        </div>
      </div>
    </div>
  );
}
