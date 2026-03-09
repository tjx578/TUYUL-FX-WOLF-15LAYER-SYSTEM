"use client";

import Link from "next/link";
import clsx from "clsx";
import { usePathname } from "next/navigation";
import AccountSwitcher from "./AccountSwitcher";
import { useAuthStore } from "@/store/useAuthStore";
import { hasRole } from "@/lib/auth";

type NavItem = {
	href: string;
	label: string;
	roles?: readonly ("viewer" | "operator" | "risk_admin" | "config_admin" | "approver")[];
};

const NAV_ITEMS: NavItem[] = [
	{ href: "/", label: "Overview" },
	{ href: "/pipeline", label: "Pipeline" },
	{ href: "/trades", label: "Trades" },
	{ href: "/accounts", label: "Accounts" },
	{ href: "/risk", label: "Risk" },
	{
		href: "/audit",
		label: "Audit",
		roles: ["risk_admin", "config_admin", "approver"],
	},
];

export default function Sidebar() {
	const pathname = usePathname();
	const user = useAuthStore((state) => state.user);

	return (
		<aside className="sidebar-root" aria-label="Primary navigation">
			<div className="sidebar-logo">
				<div className="sidebar-logo-mark" />
				<div>
					<div className="sidebar-logo-name">TUYUL FX</div>
					<div className="sidebar-logo-sub">WOLF-15 TERMINAL</div>
				</div>
			</div>

			<div className="mb-4">
				<AccountSwitcher />
			</div>

			<nav className="sidebar-nav" role="navigation" aria-label="Main menu">
				{NAV_ITEMS.filter((item) => !item.roles || hasRole(user?.role, item.roles)).map((item) => {
					const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
					return (
						<Link
							key={item.href}
							href={item.href}
							aria-current={active ? "page" : undefined}
							className={clsx("sidebar-link", active && "sidebar-link--active")}
						>
							{item.label}
						</Link>
					);
				})}
			</nav>
		</aside>
	);
}
