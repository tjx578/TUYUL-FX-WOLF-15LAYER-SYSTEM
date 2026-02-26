// Keep only local shim for libraries that do not provide complete types.

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
