"use client";

import { useEffect, useRef, useState } from "react";

export function useLivePulse<T>(value: T): boolean {
    const [pulse, setPulse] = useState(false);
    const prevRef = useRef(value);

    useEffect(() => {
        if (prevRef.current !== value) {
            prevRef.current = value;
            setPulse(true);
            const id = setTimeout(() => setPulse(false), 600);
            return () => clearTimeout(id);
        }
    }, [value]);

    return pulse;
}
