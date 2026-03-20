// Keep only local shim for libraries that do not provide complete types.

declare module 'lightweight-charts' {
  export type UTCTimestamp = number & { __brand: 'UTCTimestamp' };
  export type BusinessDay = { year: number; month: number; day: number };
  export type Time = UTCTimestamp | BusinessDay | string;

  export interface CandlestickData {
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
    color?: string;
    wickColor?: string;
    borderColor?: string;
  }

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
