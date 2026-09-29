/** Browser-facing subset of the upstream spin-wheel API used by the daily game. */
declare module 'spin-wheel' {
  export type WheelOptions = {
    items: { label: string; weight?: number }[]
    isInteractive?: boolean; pointerAngle?: number; radius?: number
    itemBackgroundColors?: string[]; itemLabelColors?: string[]
    itemLabelFontSizeMax?: number; itemLabelFont?: string; itemLabelRadius?: number
    itemLabelAlign?: string; itemLabelRotation?: number
    borderColor?: string; borderWidth?: number; lineColor?: string; lineWidth?: number
    onRest?: () => void
  }
  export class Wheel {
    constructor(container: HTMLElement, options: WheelOptions)
    spinToItem(index: number, duration?: number, center?: boolean, revolutions?: number, direction?: number): void
    getCurrentIndex(): number
    remove(): void
  }
}
