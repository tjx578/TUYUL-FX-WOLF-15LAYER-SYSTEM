import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
    return new ImageResponse(
        (
            <div
                style={{
                    background: "#050a14",
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: 6,
                    gap: 2,
                }}
            >
                <div style={{ width: 5, height: 18, background: "#c8ff1a", transform: "skew(12deg)" }} />
                <div style={{ width: 5, height: 12, background: "#c8ff1a", transform: "skew(-12deg)" }} />
                <div style={{ width: 5, height: 18, background: "#c8ff1a", transform: "skew(12deg)" }} />
            </div>
        ),
        { ...size },
    );
}
