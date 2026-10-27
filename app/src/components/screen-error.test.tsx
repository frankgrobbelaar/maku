import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScreenError } from "./screen-error";

function Broken(): never {
  throw new Error("Cannot read properties of undefined (reading 'length')");
}

describe("ScreenError", () => {
  it("shows what went wrong instead of a blank window", () => {
    vi.spyOn(console, "error").mockImplementation(() => {}); // React reports the error too

    render(
      <ScreenError>
        <Broken />
      </ScreenError>,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "This screen couldn't be shown. Nothing in your folders was touched.",
    );
    expect(alert).toHaveTextContent("Cannot read properties of undefined (reading 'length')");
    expect(screen.getByRole("button", { name: "Reload Maku" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("shows the screen when nothing goes wrong", () => {
    render(
      <ScreenError>
        <p>The library</p>
      </ScreenError>,
    );

    expect(screen.getByText("The library")).toBeInTheDocument();
  });
});
