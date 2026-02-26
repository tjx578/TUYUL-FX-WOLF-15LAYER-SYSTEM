// Module declarations for packages with missing/broken type definitions
// These are needed when npm install is incomplete or packages don't ship types

declare module 'next/link' {
  import { ComponentProps } from 'react';
  const Link: React.ForwardRefExoticComponent<
    Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & {
      href: string | { pathname: string; query?: Record<string, string> };
      prefetch?: boolean;
      replace?: boolean;
      scroll?: boolean;
      shallow?: boolean;
    } & React.RefAttributes<HTMLAnchorElement>
  >;
  export default Link;
}

declare module 'next/navigation' {
  export function usePathname(): string;
  export function useRouter(): {
    push(href: string): void;
    replace(href: string): void;
    back(): void;
    forward(): void;
    refresh(): void;
    prefetch(href: string): void;
  };
  export function useSearchParams(): URLSearchParams;
  export function useParams<T extends Record<string, string>>(): T;
  export function redirect(url: string, type?: 'push' | 'replace'): never;
  export function notFound(): never;
}

declare module 'next/image' {
  import { ComponentProps } from 'react';
  const Image: React.FC<{
    src: string;
    alt: string;
    width?: number;
    height?: number;
    fill?: boolean;
    priority?: boolean;
    className?: string;
    style?: React.CSSProperties;
  }>;
  export default Image;
}

declare module 'lucide-react' {
  import { FC, SVGProps } from 'react';
  type Icon = FC<SVGProps<SVGSVGElement> & { size?: number | string; strokeWidth?: number | string; absoluteStrokeWidth?: boolean }>;
  export const Activity: Icon;
  export const AlertTriangle: Icon;
  export const ArrowDown: Icon;
  export const ArrowUp: Icon;
  export const ArrowUpDown: Icon;
  export const Ban: Icon;
  export const BarChart3: Icon;
  export const BookOpen: Icon;
  export const Check: Icon;
  export const CheckCircle: Icon;
  export const ChevronDown: Icon;
  export const ChevronRight: Icon;
  export const Clock: Icon;
  export const Copy: Icon;
  export const DollarSign: Icon;
  export const FileText: Icon;
  export const Filter: Icon;
  export const Heart: Icon;
  export const Info: Icon;
  export const LayoutDashboard: Icon;
  export const LineChart: Icon;
  export const RefreshCw: Icon;
  export const Search: Icon;
  export const Shield: Icon;
  export const ShieldAlert: Icon;
  export const ShieldCheck: Icon;
  export const Signal: Icon;
  export const TrendingDown: Icon;
  export const TrendingUp: Icon;
  export const X: Icon;
  export const XCircle: Icon;
  export const Zap: Icon;
}

declare module 'lightweight-charts' {
  export function createChart(container: HTMLElement, options?: any): any;
  export const ColorType: {
    Solid: string;
    VerticalGradient: string;
    HorizontalGradient: string;
  };
  export const CrosshairMode: {
    Normal: number;
    Magnet: number;
  };
  export const LineStyle: {
    Solid: number;
    Dotted: number;
    Dashed: number;
    LargeDashed: number;
    SparseDotted: number;
  };
}
