import "@fontsource-variable/manrope";
import "@fontsource-variable/geist-mono";
import "./styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";
import { savedScheme, showScheme, startingScheme } from "./lib/look";

// The scheme the shell said, before the first frame; then the one it keeps, should the page have
// been reloaded since the owner chose another.
showScheme(startingScheme());
savedScheme().then(showScheme, () => {});

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element.");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
