"use client";

interface Props {
    message: string;
}

export function SignalEmptyState({ message }: Props) {
    return (
        <div
            style={{
                padding: 20,
                borderRadius: 10,
                border: "1px dashed rgba(255,255,255,0.16)",
                opacity: 0.8,
            }}
        >
            {message}
        </div>
    );
}
