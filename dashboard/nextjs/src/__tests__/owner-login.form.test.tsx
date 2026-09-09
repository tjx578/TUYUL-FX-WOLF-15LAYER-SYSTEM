import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ViewerLoginForm from "../app/login/ViewerLoginForm";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("owner login form failure handling", () => {
  it.each([401, 429, 503])("clears password after status %s", async status => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status });
    vi.stubGlobal("fetch", fetcher);
    render(<ViewerLoginForm />);
    const username = screen.getByLabelText("OWNER USERNAME") as HTMLInputElement;
    const password = screen.getByLabelText("PASSWORD") as HTMLInputElement;
    expect(username.maxLength).toBe(254);
    expect(password.maxLength).toBe(1024);
    fireEvent.change(username, { target: { value: "owner" } });
    fireEvent.change(password, { target: { value: "synthetic-form-password" } });
    fireEvent.submit(password.closest("form")!);
    await waitFor(() => expect(password.value).toBe(""));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain("synthetic-form-password");
    if (status === 429) expect(screen.getByText(/Wait one minute/)).toBeTruthy();
  });
});
