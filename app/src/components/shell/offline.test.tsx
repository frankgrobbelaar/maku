import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Offline } from "./offline";

function goes(online: boolean) {
  Object.defineProperty(navigator, "onLine", { value: online, configurable: true });
  act(() => {
    window.dispatchEvent(new Event(online ? "online" : "offline"));
  });
}

describe("Offline", () => {
  afterEach(() => goes(true));

  it("says so while the PC is offline, and goes once it's back", () => {
    render(<Offline />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    goes(false);
    expect(screen.getByRole("status")).toHaveTextContent(
      "You're offline. New titles and artwork fill in when you're back; everything else keeps working.",
    );

    goes(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
