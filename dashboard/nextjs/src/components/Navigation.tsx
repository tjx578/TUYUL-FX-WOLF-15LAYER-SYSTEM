'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import clsx from 'clsx';
import {
  LayoutDashboard,
  CandlestickChart,
  BookOpen,
  ShieldAlert,
  ArrowLeftRight,
  Activity,
} from 'lucide-react';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/chart', label: 'Chart', icon: CandlestickChart },
  { href: '/trades', label: 'Trades', icon: ArrowLeftRight },
  { href: '/journal', label: 'Journal', icon: BookOpen },
  { href: '/risk', label: 'Risk', icon: ShieldAlert },
];

export default function Navigation() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-wolf-gray bg-wolf-darker/90 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-14">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 text-wolf-gold font-bold text-lg">
            <Activity className="w-5 h-5" />
            WOLF-15
          </Link>

          {/* Nav Links */}
          <div className="flex items-center gap-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const isActive = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={clsx(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-wolf-gold/20 text-wolf-gold'
                      : 'text-gray-400 hover:text-white hover:bg-wolf-gray/50'
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              );
            })}
          </div>

          {/* Status indicator */}
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="hidden md:inline">v7.4r∞</span>
            <span className="w-2 h-2 rounded-full bg-wolf-green animate-pulse" />
          </div>
        </div>
      </div>
    </nav>
  );
}
